" Indent file for Greengold: a trailing ':' opens a block, elif/else align with if.
if exists('b:did_indent')
  finish
endif
let b:did_indent = 1

function! GgIndent(lnum) abort
  let prev = prevnonblank(a:lnum - 1)
  if prev == 0
    return 0
  endif
  let ind = indent(prev)
  let pline = substitute(getline(prev), '\s\+#.*$', '', '')
  if pline =~# ':\s*$' && pline !~# '^\s*#'
    let ind += shiftwidth()
  endif
  if getline(a:lnum) =~# '^\s*\(elif\|else\)\>' && pline !~# ':\s*$'
    let ind = max([0, ind - shiftwidth()])
  endif
  return ind
endfunction
