- when listing objects in keys.html and admin.html pages
strip the resqml20.obj_ eml20.obj_ and resqml.22. eml23.
prefixes and list alphabetically
- we should be able to multi-select the types to list

- we have several predefined preset dropdown list like the kind in globals search:
it's long, can we make sections of grouped types like wpc masterdata dataset for osdu records ... separated by line or colored, also other lists with types and objects can be very long, we can separate by type?  

- loading many objects like 200+ in global search freezes the browser we may load and cache just the content of the first 50, or create a list of 50 and next arrow for next previous 50- find useful way cache memory. so we need pagination with arrows on all object lists: in keys.html and global search.html
- pagination could also be useful for all searches for objects in rddms, in keys html and admin html, in various sections 

- [FIXED] creating ingesting manifest from selected objects :
  Ingest failed: 502 : {"detail":{"message":"Storage API PUT failed","status":400,"reason":"Bad Request","text":"{\"errors\":[\"Record otherRelevantDataCountries cannot be empty\"
  FIX: Updated osdu.py build_manifest_for_uris() to include legal fields (acl, legal, countries) in request body to RDDMS /manifests/build endpoint. This ensures otherRelevantDataCountries is properly populated (defaults to ["NO"]).


