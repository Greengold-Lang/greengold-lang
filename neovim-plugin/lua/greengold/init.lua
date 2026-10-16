-- Greengold support for Neovim. Port of the VS Code extension (vscode-extension/extension.js).
local M = {}

local uv = vim.uv or vim.loop
local is_win = vim.fn.has("win32") == 1

M.config = {
  -- Path to the `gg` executable. Empty: `gg` from PATH, then the installer folder, then python.
  path = "",
  -- Only used when `gg` is not found: runs `python -m greengold`.
  python_path = "python",
  language_server = {
    enable = true,
    -- Custom command to start the server (defaults to `gg lsp`).
    command = "",
  },
  -- Extra options merged into the vim.lsp client config (on_attach, capabilities, ...).
  lsp = {},
  debug = {
    -- "auto" | "codelldb" | "lldb" | "cppdbg" | "cppvsdbg"
    debugger = "auto",
  },
  -- "▶" sign next to `fn main` and test blocks, like CodeLens in VS Code.
  codelens = { enable = true },
  testing = { enable = true },
  format_on_save = false,
  fix_on_save = false,
  keymaps = true,
}

local configured = false

local function exepath(name)
  local p = vim.fn.exepath(name)
  return p ~= "" and p or nil
end

--- How to run the compiler: { cmd = ..., pre = { leading args } }.
function M.invocation()
  local cfg = M.config
  if cfg.path and cfg.path ~= "" then
    return { cmd = cfg.path, pre = {} }
  end
  local found = exepath("gg")
  if found then
    return { cmd = found, pre = {} }
  end
  local installed
  if is_win then
    local base = vim.env.LOCALAPPDATA or vim.fs.joinpath(vim.uv.os_homedir(), "AppData", "Local")
    installed = vim.fs.joinpath(base, "Greengold", "bin", "gg.exe")
  else
    installed = vim.fs.joinpath(vim.uv.os_homedir(), ".greengold", "bin", "gg")
  end
  if uv.fs_stat(installed) then
    return { cmd = installed, pre = {} }
  end
  return { cmd = cfg.python_path or "python", pre = { "-m", "greengold" } }
end

--- Full argv for `gg <args...>`.
function M.argv(args)
  local gg = M.invocation()
  local argv = { gg.cmd }
  vim.list_extend(argv, gg.pre)
  vim.list_extend(argv, args)
  return argv
end

local function notify(msg, level)
  vim.notify("Greengold: " .. msg, level or vim.log.levels.INFO)
end
M.notify = notify

-- ---------------------------------------------------------------- terminal

local term_buf, term_win

local function open_terminal(argv)
  if term_win and vim.api.nvim_win_is_valid(term_win) then
    vim.api.nvim_win_close(term_win, true)
  end
  if term_buf and vim.api.nvim_buf_is_valid(term_buf) then
    pcall(vim.api.nvim_buf_delete, term_buf, { force = true })
  end
  vim.cmd("botright 15new")
  term_win = vim.api.nvim_get_current_win()
  term_buf = vim.api.nvim_get_current_buf()
  local opts = { cwd = vim.fn.getcwd() }
  if vim.fn.has("nvim-0.11") == 1 then
    opts.term = true
    vim.fn.jobstart(argv, opts)
  else
    vim.fn.termopen(argv, opts)
  end
  pcall(vim.api.nvim_buf_set_name, term_buf, "Greengold")
  vim.cmd("startinsert")
end

--- Run `gg <parts>` in the terminal split.
function M.run_in_terminal(parts)
  open_terminal(M.argv(parts))
end

local function current_gg_file(silent)
  local file = vim.api.nvim_buf_get_name(0)
  if file == "" or not file:match("%.gg$") then
    if not silent then
      notify("Only .gg files can be run or built.", vim.log.levels.WARN)
    end
    return nil
  end
  if vim.bo.modified then
    vim.cmd("silent write")
  end
  return file
end

--- Run `gg <cmd> [extra] --color never <current file>`.
function M.exec(cmd, extra)
  local file = current_gg_file()
  if not file then
    return
  end
  local parts = { cmd }
  vim.list_extend(parts, extra or {})
  vim.list_extend(parts, { "--color", "never", file })
  M.run_in_terminal(parts)
end

-- ---------------------------------------------------------------- commands

function M.explain(code)
  local function go(c)
    c = vim.trim(c or "")
    if not c:upper():match("^GG%d%d%d%d$") then
      return notify("Write a code such as GG0301", vim.log.levels.WARN)
    end
    M.run_in_terminal({ "explain", c })
  end
  if code and code ~= "" then
    return go(code)
  end
  vim.ui.input({ prompt = "Diagnostic code (GG0301): " }, function(c)
    if c then
      go(c)
    end
  end)
end

function M.format()
  local file = current_gg_file()
  if not file then
    return
  end
  -- Prefer the language server; fall back to `gg fmt`.
  local clients = vim.lsp.get_clients and vim.lsp.get_clients({ bufnr = 0, name = "greengold-lsp" }) or {}
  if #clients > 0 then
    vim.lsp.buf.format({ name = "greengold-lsp", async = false })
    return
  end
  vim.system(M.argv({ "fmt", file }), { text = true }, vim.schedule_wrap(function(res)
    if res.code ~= 0 then
      return notify("fmt failed:\n" .. (res.stderr ~= "" and res.stderr or res.stdout), vim.log.levels.ERROR)
    end
    vim.cmd("silent! checktime")
  end))
end

function M.fix_all()
  vim.lsp.buf.code_action({
    context = { only = { "source.fixAll.greengold", "source.fixAll" }, diagnostics = {} },
    apply = true,
  })
end

function M.new_package()
  vim.ui.input({ prompt = "New Greengold package name: " }, function(name)
    if not name or name == "" then
      return
    end
    vim.ui.input({ prompt = "Parent directory: ", default = vim.fn.getcwd(), completion = "dir" }, function(parent)
      if not parent or parent == "" then
        return
      end
      local dir = vim.fs.joinpath(vim.fn.expand(parent), name)
      vim.system(M.argv({ "new", name, "--path", dir }), { text = true }, vim.schedule_wrap(function(res)
        if res.code ~= 0 then
          return notify("Failed to create package: " .. (res.stderr or ""), vim.log.levels.ERROR)
        end
        notify(("package '%s' created in %s"):format(name, dir))
        vim.ui.select({ "Open project (:cd)", "Stay here" }, { prompt = "Greengold" }, function(choice)
          if choice and choice:match("^Open") then
            vim.cmd("cd " .. vim.fn.fnameescape(dir))
            vim.cmd("edit " .. vim.fn.fnameescape(dir))
          end
        end)
      end)))
    end)
  end)
end

function M.bindgen(cpp, header)
  local function go(h)
    if not h or h == "" then
      return
    end
    h = vim.fn.expand(h)
    local out = h:gsub("%.[hH][pPxX]*$", "") .. ".gg"
    local args = { "bindgen" }
    if cpp then
      table.insert(args, "--cpp")
    end
    vim.list_extend(args, { h, "-o", out })
    vim.system(M.argv(args), { text = true }, vim.schedule_wrap(function(res)
      if res.code ~= 0 then
        return notify("Failed to generate bindings: " .. (res.stderr or ""), vim.log.levels.ERROR)
      end
      notify("bindings generated at " .. vim.fn.fnamemodify(out, ":t"))
      vim.cmd("edit " .. vim.fn.fnameescape(out))
    end))
  end
  if header and header ~= "" then
    return go(header)
  end
  local cur = vim.api.nvim_buf_get_name(0)
  vim.ui.input({
    prompt = cpp and "C++ header: " or "C header: ",
    default = cur:match("%.[hH]") and cur or "",
    completion = "file",
  }, go)
end

local menu = {
  { "Run Current File", "gg run", function() M.exec("run") end },
  { "Run Current File (Release)", "gg run --release", function() M.exec("run", { "--release" }) end },
  { "Debug Current File", "gg build -g, then nvim-dap", function() require("greengold.debug").debug() end },
  { "Build Binary", "gg build", function() M.exec("build") end },
  { "Build Binary (Release)", "gg build --release", function() M.exec("build", { "--release" }) end },
  { "Check Current File", "gg check", function() M.exec("check") end },
  { "Apply Safe Fixes", "gg fix", function() M.exec("fix") end },
  { "Explain Diagnostic", "gg explain GGxxxx", function() M.explain() end },
  { "Format Current File", "gg fmt", function() M.format() end },
  { "Run Tests", "gg test", function() M.exec("test") end },
  { "Run Test At Cursor", "gg test", function() require("greengold.tests").run_nearest() end },
  { "Create New Project", "gg new", function() M.new_package() end },
  { "Generate C Bindings", "gg bindgen", function() M.bindgen(false) end },
  { "Generate C++ Bindings", "gg bindgen --cpp", function() M.bindgen(true) end },
  { "Generate Documentation", "gg doc", function() M.exec("doc") end },
  { "Write API Lock", "gg api --lock", function() M.run_in_terminal({ "api", "--lock" }) end },
  { "Check API Lock", "gg api --check", function() M.run_in_terminal({ "api", "--check" }) end },
  { "List Targets", "gg targets", function() M.run_in_terminal({ "targets" }) end },
  { "Emit LLVM IR", "gg emit-ll", function() M.exec("emit-ll") end },
  { "Emit LLVM Bitcode", "gg emit-bc", function() M.exec("emit-bc") end },
  { "View AST", "gg ast", function() M.exec("ast") end },
  { "Restart Language Server", "gg lsp", function() M.restart_lsp() end },
}

function M.menu()
  vim.ui.select(menu, {
    prompt = "Greengold Development Actions",
    format_item = function(item)
      return ("%-30s %s"):format(item[1], item[2])
    end,
  }, function(item)
    if item then
      item[3]()
    end
  end)
end

-- --------------------------------------------------------------------- LSP

local function server_cmd()
  local custom = M.config.language_server.command
  if custom and custom ~= "" then
    return vim.split(vim.trim(custom), "%s+", { trimempty = true })
  end
  return M.argv({ "lsp" })
end

local function root_dir(bufnr)
  local name = vim.api.nvim_buf_get_name(bufnr)
  local found = vim.fs.find({ "gg.toml", ".git" }, { path = name, upward = true })[1]
  return found and vim.fs.dirname(found) or vim.fs.dirname(name)
end

local warned = false

function M.start_lsp(bufnr)
  if not M.config.language_server.enable then
    return
  end
  local cmd = server_cmd()
  if vim.fn.executable(cmd[1]) == 0 then
    if not warned then
      warned = true
      notify('could not start `gg`. Install it, or set `path` in require("greengold").setup().', vim.log.levels.ERROR)
    end
    return
  end
  local config = vim.tbl_deep_extend("force", {
    name = "greengold-lsp",
    cmd = cmd,
    root_dir = root_dir(bufnr),
    cmd_env = { PYTHONUNBUFFERED = "1", PYTHONIOENCODING = "utf-8" },
  }, M.config.lsp or {})
  vim.lsp.start(config, { bufnr = bufnr })
end

function M.restart_lsp()
  for _, c in ipairs(vim.lsp.get_clients({ name = "greengold-lsp" })) do
    vim.lsp.stop_client(c.id, true)
  end
  vim.defer_fn(function()
    for _, b in ipairs(vim.api.nvim_list_bufs()) do
      if vim.api.nvim_buf_is_loaded(b) and vim.bo[b].filetype == "gg" then
        M.start_lsp(b)
      end
    end
    notify("Language Server restarted.")
  end, 300)
end

-- ------------------------------------------------------------- buffer setup

local keymaps = {
  { "<leader>gr", "GgRun", "Run file" },
  { "<leader>gR", "GgRunRelease", "Run file (release)" },
  { "<leader>gd", "GgDebug", "Debug file" },
  { "<leader>gb", "GgBuild", "Build file" },
  { "<leader>gc", "GgCheck", "Check file" },
  { "<leader>gt", "GgTest", "Run tests" },
  { "<leader>gn", "GgTestNearest", "Run test at cursor" },
  { "<leader>gf", "GgFormat", "Format file" },
  { "<leader>gm", "GgMenu", "Greengold menu" },
}

function M._attach(bufnr)
  if not configured then
    M.setup({})
  end
  M.start_lsp(bufnr)
  if M.config.keymaps then
    for _, k in ipairs(keymaps) do
      vim.keymap.set("n", k[1], "<cmd>" .. k[2] .. "<cr>", { buffer = bufnr, desc = "Greengold: " .. k[3], silent = true })
    end
  end
  if M.config.codelens.enable or M.config.testing.enable then
    require("greengold.tests").attach(bufnr)
  end
  local group = vim.api.nvim_create_augroup("GreengoldSave" .. bufnr, { clear = true })
  if M.config.fix_on_save or M.config.format_on_save then
    vim.api.nvim_create_autocmd("BufWritePre", {
      group = group,
      buffer = bufnr,
      callback = function()
        if M.config.fix_on_save then
          pcall(M.fix_all)
        end
        if M.config.format_on_save then
          pcall(vim.lsp.buf.format, { name = "greengold-lsp", async = false })
        end
      end,
    })
  end
end

function M.register_commands()
  local function cmd(name, fn, opts)
    vim.api.nvim_create_user_command(name, fn, opts or {})
  end
  cmd("GgRun", function() M.exec("run") end)
  cmd("GgRunRelease", function() M.exec("run", { "--release" }) end)
  cmd("GgDebug", function() require("greengold.debug").debug() end)
  cmd("GgBuild", function() M.exec("build") end)
  cmd("GgBuildRelease", function() M.exec("build", { "--release" }) end)
  cmd("GgCheck", function() M.exec("check") end)
  cmd("GgFix", function() M.exec("fix") end)
  cmd("GgFixAll", function() M.fix_all() end)
  cmd("GgExplain", function(o) M.explain(o.args) end, { nargs = "?" })
  cmd("GgFormat", function() M.format() end)
  cmd("GgTest", function() M.exec("test") end)
  cmd("GgTestNearest", function() require("greengold.tests").run_nearest() end)
  cmd("GgDoc", function() M.exec("doc") end)
  cmd("GgNew", function() M.new_package() end)
  cmd("GgBindgen", function(o) M.bindgen(false, o.args) end, { nargs = "?", complete = "file" })
  cmd("GgBindgenCpp", function(o) M.bindgen(true, o.args) end, { nargs = "?", complete = "file" })
  cmd("GgApiLock", function() M.run_in_terminal({ "api", "--lock" }) end)
  cmd("GgApiCheck", function() M.run_in_terminal({ "api", "--check" }) end)
  cmd("GgTargets", function() M.run_in_terminal({ "targets" }) end)
  cmd("GgEmitLLVM", function() M.exec("emit-ll") end)
  cmd("GgEmitBC", function() M.exec("emit-bc") end)
  cmd("GgAst", function() M.exec("ast") end)
  cmd("GgMenu", function() M.menu() end)
  cmd("GgRestartServer", function() M.restart_lsp() end)
end

local function register_icons()
  local ok, devicons = pcall(require, "nvim-web-devicons")
  if ok and devicons.set_icon then
    devicons.set_icon({
      gg = {
        icon = "󰘧",
        color = "#4CAF50",
        cterm_color = "71",
        name = "Greengold",
      },
    })
  end
  local ok2, mini_icons = pcall(require, "mini.icons")
  if ok2 and mini_icons.set then
    pcall(mini_icons.set, "extension", "gg", { style = "Greengold", glyph = "󰘧", hl = "MiniIconsGreen" })
  end
end

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
  configured = true
  register_icons()
end

return M
