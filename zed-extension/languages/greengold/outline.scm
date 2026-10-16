(function_item
  "fn" @context
  name: (identifier) @name) @item

(type_item
  _ @context
  name: (identifier) @name) @item

(impl_item
  "impl" @context
  name: (identifier) @name) @item

(test_item
  "test" @context
  name: (identifier)? @name) @item
