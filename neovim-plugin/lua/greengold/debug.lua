-- Native debugging through nvim-dap (mirrors debugCurrentFile).
local M = {}

local function exe_path(file)
  local ext = vim.fn.has("win32") == 1 and ".exe" or ""
  return vim.fs.joinpath(vim.fs.dirname(file), vim.fn.fnamemodify(file, ":t:r") .. ext)
end

local function pick_adapter()
  local want = require("greengold").config.debug.debugger
  if want ~= "auto" then
    return want
  end
  if vim.fn.executable("codelldb") == 1 then
    return "codelldb"
  elseif vim.fn.executable("lldb-dap") == 1 or vim.fn.executable("lldb-vscode") == 1 then
    return "lldb"
  elseif vim.fn.executable("gdb") == 1 then
    return "cppdbg"
  end
  return "codelldb"
end

function M.debug()
  local gg = require("greengold")
  local ok, dap = pcall(require, "dap")
  if not ok then
    return gg.notify("nvim-dap is required for debugging (https://github.com/mfussenegger/nvim-dap).", vim.log.levels.WARN)
  end
  local file = vim.api.nvim_buf_get_name(0)
  if not file:match("%.gg$") then
    return gg.notify("Please open a Greengold (.gg) file to debug.", vim.log.levels.WARN)
  end
  if vim.bo.modified then
    vim.cmd("silent write")
  end
  local out = exe_path(file)
  gg.notify("building " .. vim.fn.fnamemodify(file, ":t:r") .. " for debugging...")
  vim.system(gg.argv({ "build", "-g", "--color", "never", file, "-o", out }), { text = true }, vim.schedule_wrap(function(res)
    if res.code ~= 0 then
      return gg.notify("build failed:\n" .. (res.stderr ~= "" and res.stderr or res.stdout), vim.log.levels.ERROR)
    end
    if not vim.uv.fs_stat(out) then
      return gg.notify("build succeeded but the binary was not found at " .. out, vim.log.levels.ERROR)
    end
    local adapter = pick_adapter()
    local config = {
      name = "Debug: " .. vim.fn.fnamemodify(file, ":t:r"),
      type = adapter,
      request = "launch",
      program = out,
      cwd = vim.fs.dirname(file),
      args = {},
      stopOnEntry = false,
      stopAtEntry = false,
    }
    if adapter == "cppdbg" then
      config.MIMode = vim.fn.has("mac") == 1 and "lldb" or "gdb"
    end
    dap.run(config)
  end))
end

return M
