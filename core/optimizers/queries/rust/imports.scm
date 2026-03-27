((use_declaration
   (use_as_clause
     path: (scoped_identifier) @import.module
     alias: (identifier) @import.alias)) @import.statement)
((use_declaration
   (scoped_identifier) @import.module) @import.statement)
