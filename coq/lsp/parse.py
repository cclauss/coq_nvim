from random import shuffle
from typing import Any, Mapping, MutableSequence, Optional, Sequence, cast

from pynvim_pp.logging import log

from ..shared.types import UTF16, Completion, Doc, Edit, Extern, RangeEdit, SnippetEdit
from .protocol import PROTOCOL
from .types import CompletionItem, CompletionResponse, LSPcomp, TextEdit


def _falsy(thing: Any) -> bool:
    return thing is None or thing == False or thing == 0 or thing == "" or thing == b""


def _range_edit(edit: TextEdit) -> Optional[RangeEdit]:
    rg = edit.get("range", {})
    s, e = rg.get("start", {}), rg.get("end", {})
    b_r, b_c = s.get("line"), s.get("character")
    e_r, e_c = e.get("line"), e.get("character")
    new_text = edit.get("newText")
    if (
        new_text
        and b_r is not None
        and b_c is not None
        and e_r is not None
        and e_c is not None
    ):
        begin = b_r, b_c
        end = e_r, e_c
        return RangeEdit(new_text=new_text, begin=begin, end=end, encoding=UTF16)
    else:
        return None


def _primary(item: CompletionItem) -> Edit:
    text_edit = item.get("textEdit")
    fall_back = item.get("insertText") or item.get("label") or ""

    if PROTOCOL.InsertTextFormat.get(item.get("insertTextFormat")) == "Snippet":
        if isinstance(text_edit, Mapping) and "range" in text_edit:
            new_text = text_edit.get("newText") or fall_back
        else:
            new_text = fall_back
        return SnippetEdit(grammar="lsp", new_text=new_text)

    elif isinstance(text_edit, Mapping):
        # TODO -- InsertReplaceEdit
        # if "insert" in text_edit:
        #     return Edit(new_text=fall_back)
        if "range" in text_edit:
            re = _range_edit(cast(TextEdit, text_edit))
            if re:
                return re
            else:
                return Edit(new_text=fall_back)
        else:
            return Edit(new_text=fall_back)
    else:
        return Edit(new_text=fall_back)


def doc(item: CompletionItem) -> Optional[Doc]:
    doc = item.get("documentation")
    detail = item.get("detail")
    if isinstance(doc, Mapping):
        markup, kind = doc.get("value"), doc.get("kind")
        if markup and kind:
            return Doc(text=markup, syntax=kind)
        else:
            return None
    elif isinstance(doc, str):
        return Doc(text=doc, syntax="")
    elif detail:
        return Doc(text=detail, syntax="")
    else:
        return None


def _parse_item(
    short_name: str, tie_breaker: int, item: CompletionItem
) -> Optional[Completion]:
    label = item.get("label")
    if not label:
        return None
    else:
        p_edit = _primary(item)
        cmp = Completion(
            source=short_name,
            tie_breaker=tie_breaker,
            label=label,
            sort_by=item.get("filterText") or p_edit.new_text,
            primary_edit=p_edit,
            secondary_edits=tuple(
                re
                for re in map(_range_edit, item.get("additionalTextEdits") or ())
                if re
            ),
            kind=PROTOCOL.CompletionItemKind.get(item.get("kind"), ""),
            doc=doc(item),
            extern=(Extern.lsp, item),
        )
        return cmp


def parse(short_name: str, tie_breaker: int, resp: CompletionResponse) -> LSPcomp:
    if _falsy(resp):
        return LSPcomp(local_cache=False, items=iter(()))

    elif isinstance(resp, Mapping):
        is_complete = _falsy(resp.get("isIncomplete"))
        items = resp.get("items", [])
        shuffle(cast(MutableSequence, items))
        comps = (
            c
            for c in (
                _parse_item(short_name, tie_breaker=tie_breaker, item=item)
                for item in items
            )
            if c
        )
        lc = LSPcomp(local_cache=is_complete, items=comps)
        return lc

    elif isinstance(resp, Sequence) and not isinstance(cast(Any, resp), str):
        shuffle(cast(MutableSequence, resp))
        comps = (
            c
            for c in (
                _parse_item(short_name, tie_breaker=tie_breaker, item=item)
                for item in resp
            )
            if c
        )
        return LSPcomp(local_cache=True, items=comps)

    else:
        msg = f"Unknown LSP resp -- {type(resp)}"
        log.warn("%s", msg)
        return LSPcomp(local_cache=False, items=iter(()))
