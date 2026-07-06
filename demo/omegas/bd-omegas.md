TODO:
- create a osdu business decision manifest (analogous to drogon dg2 but now for a pre-drill well plan decision as in demo/omega folder. we have one exloration well 19S and plan the bd for one production well and one injector well (we create two new bd well records).
- include evidence package as persistedcollection wpc, and create a collaboration project for the field development (use appropriate titles names, structure, as in the ppt), include the rddms dataspace, and data (exported from dsg project and rms: well plan, surfaces seismic reference ...), maybe another persisted collection for drilling related data  Activities, Trajectory, Risks, Fluid and Cementing, Rig utilization, Reports / Daily Drilling Reports Equipment used – tubulars, BHA ...
- folder omegas/resqml contains the resqml files exported from the rms 15 project "/project/snorre/reservoirmodels/omegasor/2026.2.0/rms/model/os.rms15.0.1.0"
this needs to be ingested to reservoir ddms eqndev instance to maap/omegas dataspace same way as other drogon demos (we have a pipeline, can use the local rddms etpserver and client to push it to eqndev, see /home/maap/ores/demo/drogonresqml/docker-compose.yaml to use it and drogon pipeline example)
- the volume table shall be created using osdu names and propertykinds etc, from the os.val...xls tables. and ingested to the eqndev catalog
- we need to create the manifest for the maap/omegas dataspace and ingets to search catalog eqndev, we can use the eqndev manifest generator (we have the rest api link in ores admin.html page?). 
- Create the CollaborationProject for "Snorre Omega sor" and BusinessDecision WPC for the new development well, include all relevant information from the pptx for the well t be drilled (NOT the entire fielde development decision - just the well decision!)

- Create persistedCollection for all Artefacts  
