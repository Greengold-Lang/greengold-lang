-- Mirrors "configurationDefaults" of the VS Code extension for [gg].
local bo = vim.bo
bo.commentstring = "# %s"
bo.comments = ":#"
bo.expandtab = true
bo.shiftwidth = 4
bo.softtabstop = 4
bo.tabstop = 4
bo.indentexpr = "GgIndent(v:lnum)"
bo.indentkeys = "0{,0},0),0],!^F,o,O,0=elif,0=else"
bo.formatoptions = bo.formatoptions:gsub("t", "") .. "croql"

vim.b.undo_ftplugin = "setl cms< com< et< sw< sts< ts< inde< indk< fo<"

require("greengold")._attach(vim.api.nvim_get_current_buf())
