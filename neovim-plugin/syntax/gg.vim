" Vim syntax file
" Language:   Greengold (.gg)
" Generated from vscode-extension/syntaxes/gg.tmLanguage.json

if exists('b:current_syntax')
  finish
endif

syn case match

syn keyword ggTodo        contained TODO FIXME XXX NOTE HACK
syn match   ggComment     "#.*$" contains=ggTodo,@Spell

" Strings and characters
syn match   ggEscape      contained "\\[ntr\\'\"0]"
syn region  ggString      start=+"+ skip=+\\\\\|\\"+ end=+"+ oneline contains=ggEscape,@Spell
syn match   ggChar        "'\([^'\\]\|\\[ntr\\'\"0]\)'" contains=ggEscape

" Numbers
syn match   ggNumber      "\<[0-9][0-9_]*\>"
syn match   ggFloat       "\<[0-9][0-9_]*\.[0-9][0-9_]*\>"
syn match   ggHex         "\<0[xX][0-9a-fA-F][0-9a-fA-F_]*\>"
syn match   ggBin         "\<0[bB][01][01_]*\>"

" Keywords
syn keyword ggConditional if elif else then match
syn keyword ggRepeat      while for in step
syn keyword ggFlow        return break continue pass defer await
syn keyword ggOperatorKw  and or not
syn keyword ggStatement   import require allocator test
syn keyword ggDeclaration fn struct enum union feature impl extern
syn keyword ggModifier    public private hot trust fixed const static weak unsafe comptime async
syn keyword ggModifier    copy soa exclusive packed align wrapping overflow wrap trap
syn keyword ggMode        consume lend read send
syn keyword ggModifier    tied to dyn ref mut as
syn keyword ggBoolean     true false
syn keyword ggConstant    null Valid None Ok Err
syn keyword ggSelf        self
syn keyword ggWildcard    _

" Types
syn keyword ggType        i8 i16 i32 i64 isize u8 u16 u32 u64 usize f32 f64
syn keyword ggType        int uint float double bool str void Self
syn keyword ggType        f32x4 f32x8 f64x2 f64x4 i32x4 i32x8 i64x2 i64x4 i16x8 u8x16 u32x4
syn keyword ggType        Optional Result Box List Shared Arc Fn string Tuple2 Tuple3 Tuple4 Tuple5 Tuple6
syn keyword ggType        Num Int Float Ord Eq Key
syn match   ggTypeName    "\<[A-Z][A-Za-z0-9_]*\>"

" Declarations: highlight the declared name
syn match   ggFnName      "\<fn\s\+\zs[A-Za-z_][A-Za-z0-9_]*"
syn match   ggTypeDecl    "\<\(struct\|enum\|union\|feature\)\s\+\zs[A-Za-z_][A-Za-z0-9_]*"

" Calls and builtins
syn match   ggCall        "\<[a-z_][A-Za-z0-9_]*\ze\s*[(\[]"
syn match   ggMethod      "\.\zs[A-Za-z_][A-Za-z0-9_]*\ze\s*("
syn keyword ggBuiltin     print eprint panic input addr addr_mut ptr_offset ptr_to_int int_to_ptr
syn keyword ggBuiltin     cstr_to_string string_to_cstr str_from_raw ptr_read ptr_write ptr_cast
syn keyword ggBuiltin     volatile_read volatile_write atomic_load atomic_store atomic_add atomic_sub
syn keyword ggBuiltin     atomic_and atomic_or atomic_xor atomic_swap atomic_cas fence size_of align_of
syn keyword ggBuiltin     add_overflows sub_overflows mul_overflows max_value min_value target_os
syn keyword ggBuiltin     target_arch hash asm wrapping_add wrapping_sub wrapping_mul saturating_add
syn keyword ggBuiltin     saturating_sub saturating_mul checked_add checked_sub checked_mul

" Operators
syn match   ggOperator    "=>\|->\|\.\.\.\|\.\.=\|\.\.\|?\|<<=\|>>=\|[-+*/%&|^]=\|==\|!=\|<=\|>=\|<<\|>>\|[-+*/%&|^~<>=]"

hi def link ggTodo        Todo
hi def link ggComment     Comment
hi def link ggString      String
hi def link ggChar        Character
hi def link ggEscape      SpecialChar
hi def link ggNumber      Number
hi def link ggFloat       Float
hi def link ggHex         Number
hi def link ggBin         Number
hi def link ggConditional Conditional
hi def link ggRepeat      Repeat
hi def link ggFlow        Keyword
hi def link ggOperatorKw  Operator
hi def link ggStatement   Statement
hi def link ggDeclaration Keyword
hi def link ggModifier    StorageClass
hi def link ggMode        StorageClass
hi def link ggBoolean     Boolean
hi def link ggConstant    Constant
hi def link ggSelf        Identifier
hi def link ggWildcard    Special
hi def link ggType        Type
hi def link ggTypeName    Type
hi def link ggTypeDecl    Type
hi def link ggFnName      Function
hi def link ggCall        Function
hi def link ggMethod      Function
hi def link ggBuiltin     Special
hi def link ggOperator    Operator

let b:current_syntax = 'gg'
