-- Greengold Color Theme for Neovim (port of VS Code Greengold Dark / Light)
local M = {}

local palettes = {
  dark = {
    bg = "#0b100d",
    bg_alt = "#0d1310",
    bg_subtle = "#101813",
    bg_highlight = "#15201a",
    selection = "#1f3a2c",
    border = "#1f2c25",
    fg = "#d9e3db",
    fg_muted = "#8a9a90",
    fg_subtle = "#55665c",
    line_nr = "#45554b",
    cursor = "#f2c443",
    gold = "#f2c443",
    gold_light = "#f7dc8c",
    green = "#5fe0a0",
    green_accent = "#3fd08a",
    lime = "#c7e37b",
    blue = "#8fd3ff",
    orange = "#f0a476",
    red = "#ff8a80",
    comment = "#6c7d72",
    property = "#b9cbbf",
    operator = "#9fb3a6",
  },
  light = {
    bg = "#f7faf8",
    bg_alt = "#f2f7f4",
    bg_subtle = "#f0f5f1",
    bg_highlight = "#eef4f0",
    selection = "#cde5d5",
    border = "#d2ded5",
    fg = "#1f2b24",
    fg_muted = "#66746b",
    fg_subtle = "#8e9b92",
    line_nr = "#8e9b92",
    cursor = "#8f5f00",
    gold = "#8f5f00",
    gold_light = "#7a5300",
    green = "#0f7a47",
    green_accent = "#1f9d63",
    lime = "#5f7a00",
    blue = "#1f63a8",
    orange = "#b04a1c",
    red = "#c2352b",
    comment = "#7b897f",
    property = "#3b4a41",
    operator = "#55655b",
  },
}

function M.apply(variant)
  variant = variant or "dark"
  local p = palettes[variant] or palettes.dark

  vim.cmd("hi clear")
  if vim.fn.exists("syntax_on") == 1 then
    vim.cmd("syntax reset")
  end

  vim.o.termguicolors = true
  vim.o.background = variant
  vim.g.colors_name = variant == "light" and "greengold-light" or "greengold"

  local hl = function(name, opts)
    vim.api.nvim_set_hl(0, name, opts)
  end

  -- Base UI
  hl("Normal", { fg = p.fg, bg = p.bg })
  hl("NormalFloat", { fg = p.fg, bg = p.bg_alt })
  hl("FloatBorder", { fg = p.border, bg = p.bg_alt })
  hl("Cursor", { fg = p.bg, bg = p.cursor })
  hl("CursorLine", { bg = p.bg_highlight })
  hl("CursorLineNr", { fg = p.gold, bold = true })
  hl("LineNr", { fg = p.line_nr })
  hl("SignColumn", { bg = p.bg })
  hl("ColorColumn", { bg = p.bg_highlight })
  hl("Visual", { bg = p.selection })
  hl("VisualNOS", { bg = p.selection })
  hl("Search", { fg = p.bg, bg = p.gold })
  hl("IncSearch", { fg = p.bg, bg = p.green_accent })
  hl("CurSearch", { fg = p.bg, bg = p.green_accent })
  hl("Pmenu", { fg = p.fg, bg = p.bg_subtle })
  hl("PmenuSel", { fg = p.fg, bg = p.selection, bold = true })
  hl("PmenuSbar", { bg = p.bg_subtle })
  hl("PmenuThumb", { bg = p.border })
  hl("StatusLine", { fg = p.fg, bg = p.bg_alt })
  hl("StatusLineNC", { fg = p.fg_subtle, bg = p.bg_alt })
  hl("VertSplit", { fg = p.border, bg = p.bg })
  hl("WinSeparator", { fg = p.border, bg = p.bg })
  hl("Folded", { fg = p.comment, bg = p.bg_highlight })
  hl("FoldColumn", { fg = p.comment, bg = p.bg })
  hl("TabLine", { fg = p.fg_muted, bg = p.bg_alt })
  hl("TabLineSel", { fg = p.fg, bg = p.bg, bold = true })
  hl("TabLineFill", { bg = p.bg_alt })

  -- Syntax
  hl("Comment", { fg = p.comment, italic = true })
  hl("Constant", { fg = p.lime })
  hl("String", { fg = p.orange })
  hl("Character", { fg = p.orange })
  hl("Number", { fg = p.lime })
  hl("Boolean", { fg = p.lime })
  hl("Float", { fg = p.lime })
  hl("Identifier", { fg = p.fg })
  hl("Function", { fg = p.blue })
  hl("Statement", { fg = p.green })
  hl("Conditional", { fg = p.green })
  hl("Repeat", { fg = p.green })
  hl("Label", { fg = p.green })
  hl("Operator", { fg = p.operator })
  hl("Keyword", { fg = p.green })
  hl("Exception", { fg = p.red })
  hl("PreProc", { fg = p.green })
  hl("Type", { fg = p.gold })
  hl("StorageClass", { fg = p.green })
  hl("Structure", { fg = p.gold })
  hl("Typedef", { fg = p.gold })
  hl("Special", { fg = p.lime })
  hl("SpecialChar", { fg = p.lime })
  hl("Tag", { fg = p.gold })
  hl("Delimiter", { fg = p.operator })
  hl("Underlined", { underline = true })
  hl("Error", { fg = p.red, bold = true })
  hl("Todo", { fg = p.gold, bold = true })

  -- TreeSitter & LSP
  hl("@comment", { link = "Comment" })
  hl("@string", { link = "String" })
  hl("@string.escape", { fg = p.lime })
  hl("@character", { link = "Character" })
  hl("@number", { link = "Number" })
  hl("@boolean", { link = "Boolean" })
  hl("@float", { link = "Float" })
  hl("@function", { link = "Function" })
  hl("@function.builtin", { fg = p.blue })
  hl("@function.call", { link = "Function" })
  hl("@function.method", { link = "Function" })
  hl("@method", { link = "Function" })
  hl("@keyword", { link = "Keyword" })
  hl("@keyword.function", { link = "Keyword" })
  hl("@keyword.operator", { fg = p.green })
  hl("@keyword.return", { link = "Keyword" })
  hl("@operator", { link = "Operator" })
  hl("@type", { link = "Type" })
  hl("@type.builtin", { fg = p.gold_light })
  hl("@property", { fg = p.property })
  hl("@variable", { fg = p.fg })
  hl("@variable.builtin", { fg = p.green, italic = true })
  hl("@variable.parameter", { fg = p.fg })
  hl("@constant", { link = "Constant" })
  hl("@constant.builtin", { link = "Constant" })
  hl("@punctuation.bracket", { fg = p.operator })
  hl("@punctuation.delimiter", { fg = p.operator })

  -- Diagnostics
  hl("DiagnosticError", { fg = p.red })
  hl("DiagnosticWarn", { fg = p.gold })
  hl("DiagnosticInfo", { fg = p.blue })
  hl("DiagnosticHint", { fg = p.green_accent })
  hl("DiagnosticOk", { fg = p.green_accent })
  hl("DiagnosticUnderlineError", { undercurl = true, sp = p.red })
  hl("DiagnosticUnderlineWarn", { undercurl = true, sp = p.gold })
  hl("DiagnosticUnderlineInfo", { undercurl = true, sp = p.blue })
  hl("DiagnosticUnderlineHint", { undercurl = true, sp = p.green_accent })

  -- Git / Diff
  hl("DiffAdd", { fg = p.green_accent, bg = p.selection })
  hl("DiffChange", { fg = p.gold, bg = p.bg_highlight })
  hl("DiffDelete", { fg = p.red, bg = p.bg_highlight })
  hl("DiffText", { fg = p.gold, bold = true })
end

return M
