((function_declaration name: (identifier) @function.name) @function.definition)
((class_declaration name: (type_identifier) @class.name) @class.definition)
((lexical_declaration
   (variable_declarator name: (identifier) @assignment.name)) @assignment.definition)
