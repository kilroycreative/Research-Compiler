((import_statement
   (dotted_name) @import.module) @import.statement)
((import_from_statement
   (dotted_name) @import.module
   (aliased_import
     name: (dotted_name) @import.name
     alias: (identifier) @import.alias)) @import.statement)
((import_from_statement
   (dotted_name) @import.module
   (dotted_name) @import.name) @import.statement)
