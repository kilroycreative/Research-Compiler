((import_statement
   (string (string_fragment) @import.module)) @import.statement)
((import_statement
   (import_clause (identifier) @import.alias)
   (string (string_fragment) @import.module)) @import.statement)
((import_statement
   (import_clause
     (named_imports
       (import_specifier
         name: (identifier) @import.name
         alias: (identifier) @import.alias)))
   (string (string_fragment) @import.module)) @import.statement)
((import_statement
   (import_clause
     (named_imports
       (import_specifier
         name: (identifier) @import.name)))
   (string (string_fragment) @import.module)) @import.statement)
