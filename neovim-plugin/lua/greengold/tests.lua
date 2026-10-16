-- Test discovery and runner (port of findGreengoldTests / runTestProfile).
local M = {}

local ns = vim.api.nvim_create_namespace("greengold_tests")
local diag_ns = vim.api.nvim_create_namespace("greengold_test_results")

--- Returns a list of { name, line (0-based), character (0-based) }.
function M.find_tests(lines)
  local tests, seen = {}, {}
  local target, impl_owner = "", ""

  local function push(base, i, ch)
    local n = (seen[base] or 0) + 1
    seen[base] = n
    tests[#tests + 1] = { name = n == 1 and base or (base .. "." .. n), line = i, character = math.max(ch, 0) }
  end

  for i, line in ipairs(lines) do
    local code = line:gsub("%s+#.*$", "")
    local top = not line:match("^%s")
    if top then
      local owner = code:match("^impl%s+[%a_][%w_]*%.([%a_][%w_]*)") or code:match("^impl%s+([%a_][%w_]*)")
      if owner then
        impl_owner = owner
      else
        local fn = code:match("^hot%s+fn%s+([%a_][%w_]*)") or code:match("^comptime%s+fn%s+([%a_][%w_]*)")
          or code:match("^fn%s+([%a_][%w_]*)")
        if fn then
          impl_owner = ""
          target = fn
          if fn:match("^test_[%w_]+$") and code:match("%(%s*%)%s*:") and not code:match("%)%s*%->") then
            push(fn, i - 1, (line:find(fn, 1, true) or 1) - 1)
          end
        else
          local explicit = code:match("^test%s+([%a_][%w_]*)%s*:")
          local bare = code:match("^test%s*:")
          if explicit or bare then
            local base
            if explicit then
              base = target ~= "" and (target .. "." .. explicit) or explicit
            else
              base = target ~= "" and (target .. ".test") or "test"
            end
            push(base, i - 1, 0)
          elseif code:match("%S") and not code:match("^#") then
            impl_owner = ""
          end
        end
      end
    else
      local method = code:match("^%s+hot%s+fn%s+([%a_][%w_]*)") or code:match("^%s+fn%s+([%a_][%w_]*)")
      if method and impl_owner ~= "" then
        target = impl_owner .. "." .. method
      end
    end
  end
  return tests
end

local function buf_lines(bufnr)
  return vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
end

local function decorate(bufnr)
  if not vim.api.nvim_buf_is_valid(bufnr) then
    return
  end
  vim.api.nvim_buf_clear_namespace(bufnr, ns, 0, -1)
  local cfg = require("greengold").config
  local lines = buf_lines(bufnr)
  if cfg.codelens.enable then
    for i, line in ipairs(lines) do
      if line:match("^fn%s+main%(%)%s*:") then
        vim.api.nvim_buf_set_extmark(bufnr, ns, i - 1, 0, {
          virt_text = { { "  ▶ Run  ⚡ Release  🐞 Debug  (:GgRun :GgRunRelease :GgDebug)", "Comment" } },
          virt_text_pos = "eol",
        })
      end
    end
  end
  for _, t in ipairs(M.find_tests(lines)) do
    vim.api.nvim_buf_set_extmark(bufnr, ns, t.line, 0, {
      sign_text = "▶",
      sign_hl_group = "DiagnosticOk",
      virt_text = cfg.codelens.enable and { { "  ▶ Run Test (:GgTestNearest)", "Comment" } } or nil,
      virt_text_pos = "eol",
    })
  end
end

function M.attach(bufnr)
  decorate(bufnr)
  local group = vim.api.nvim_create_augroup("GreengoldTests" .. bufnr, { clear = true })
  vim.api.nvim_create_autocmd({ "BufWritePost", "InsertLeave", "TextChanged" }, {
    group = group,
    buffer = bufnr,
    callback = function()
      decorate(bufnr)
    end,
  })
end

--- Run `gg test --json` on the file; report results as diagnostics.
--- `only` limits the notification to one test name.
function M.run_file(bufnr, only)
  local gg = require("greengold")
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  local file = vim.api.nvim_buf_get_name(bufnr)
  if not file:match("%.gg$") then
    return gg.notify("Please open a Greengold file first.", vim.log.levels.WARN)
  end
  if vim.bo[bufnr].modified then
    vim.api.nvim_buf_call(bufnr, function()
      vim.cmd("silent write")
    end)
  end
  gg.notify("running tests...")
  vim.system(gg.argv({ "test", "--json", "--color", "never", file }), { text = true, cwd = vim.fs.dirname(file) },
    vim.schedule_wrap(function(res)
      local ok, doc = pcall(vim.json.decode, res.stdout or "")
      if not ok or type(doc) ~= "table" or type(doc.tests) ~= "table" then
        local msg = vim.trim((res.stderr ~= "" and res.stderr) or res.stdout or "gg test failed")
        return gg.notify(msg, vim.log.levels.ERROR)
      end
      local diagnostics, passed, failed, shown = {}, 0, 0, false
      for _, r in ipairs(doc.tests) do
        if r.status == "passed" then
          passed = passed + 1
          if only and r.name == only then
            gg.notify(("✔ %s passed"):format(r.name))
            shown = true
          end
        else
          failed = failed + 1
          local line = tonumber(r.line)
          diagnostics[#diagnostics + 1] = {
            lnum = line and line > 0 and line - 1 or 0,
            col = 0,
            severity = vim.diagnostic.severity.ERROR,
            source = "gg test",
            message = ("%s: %s"):format(r.name, r.message or "failed"),
          }
          if only and r.name == only then
            gg.notify(("✘ %s failed: %s"):format(r.name, r.message or ""), vim.log.levels.ERROR)
            shown = true
          end
        end
      end
      vim.diagnostic.set(diag_ns, bufnr, diagnostics)
      if not shown then
        gg.notify(("%d passed, %d failed"):format(passed, failed), failed > 0 and vim.log.levels.ERROR or vim.log.levels.INFO)
      end
    end))
end

--- Run the tests of the file and report the test at (or above) the cursor.
function M.run_nearest()
  local bufnr = vim.api.nvim_get_current_buf()
  local row = vim.api.nvim_win_get_cursor(0)[1] - 1
  local best
  for _, t in ipairs(M.find_tests(buf_lines(bufnr))) do
    if t.line <= row then
      best = t
    end
  end
  M.run_file(bufnr, best and best.name or nil)
end

return M
