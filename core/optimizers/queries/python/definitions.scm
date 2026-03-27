((function_definition name: (identifier) @function.name) @function.definition)
((class_definition name: (identifier) @class.name) @class.definition)
((assignment (identifier) @assignment.name) @assignment.definition)
((class_definition
   name: (identifier) @class.name
   (block
     ((function_definition name: (identifier) @method.name) @method.definition))))
