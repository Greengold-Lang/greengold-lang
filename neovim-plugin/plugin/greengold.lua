if vim.g.loaded_greengold then
  return
end
vim.g.loaded_greengold = true

require("greengold").register_commands()
