<!-- Generated from manuals/cl/native-applications.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# native-applications

## office
CL 1
L native-applications v1 -- Owned native document, version and render workflow
T t1 json:"{\"type\":\"object\"}"
A neyvia.nativeapp.edit(sessionId:str value:str) -> t1 ! -- Revise the owned native draft, Git note or browser card input
C neyvia.nativeapp.edit revision1:neyvia.nativeapp.observe(expected:value1 persisted:false sessionId:sessionId) .ok == true
A neyvia.nativeapp.edit(sessionId:str value:str) -> t1 ! -- Revise the owned native draft, Git note or browser card input
C neyvia.nativeapp.edit revision2:neyvia.nativeapp.observe(expected:value2 persisted:false sessionId:sessionId) .ok == true
A neyvia.nativeapp.edit(sessionId:str value:str) -> t1 ! -- Revise the owned native draft, Git note or browser card input
C neyvia.nativeapp.edit revision3:neyvia.nativeapp.observe(expected:value3 persisted:false sessionId:sessionId) .ok == true
A neyvia.nativeapp.edit(sessionId:str value:str) -> t1 ! -- Revise the owned native draft, Git note or browser card input
C neyvia.nativeapp.edit revision4:neyvia.nativeapp.observe(expected:value4 persisted:false sessionId:sessionId) .ok == true
A neyvia.nativeapp.edit(sessionId:str value:str) -> t1 ! -- Revise the owned native draft, Git note or browser card input
C neyvia.nativeapp.edit revision5:neyvia.nativeapp.observe(expected:value5 persisted:false sessionId:sessionId) .ok == true
A neyvia.nativeapp.persist(sessionId:str) -> t1 ! -- Save and reopen a document, commit a local note, or render a card
C neyvia.nativeapp.persist persist:neyvia.nativeapp.observe(expected:value5 persisted:true sessionId:sessionId) .ok == true
C neyvia.nativeapp.observe revision1:neyvia.nativeapp.observe(expected:value1 persisted:false sessionId:sessionId) .ok == true
C neyvia.nativeapp.observe revision2:neyvia.nativeapp.observe(expected:value2 persisted:false sessionId:sessionId) .ok == true
C neyvia.nativeapp.observe revision3:neyvia.nativeapp.observe(expected:value3 persisted:false sessionId:sessionId) .ok == true
C neyvia.nativeapp.observe revision4:neyvia.nativeapp.observe(expected:value4 persisted:false sessionId:sessionId) .ok == true
C neyvia.nativeapp.observe revision5:neyvia.nativeapp.observe(expected:value5 persisted:false sessionId:sessionId) .ok == true
C neyvia.nativeapp.observe persist:neyvia.nativeapp.observe(expected:value5 persisted:true sessionId:sessionId) .ok == true
P revise-save-reopen(sessionId:str value1:str value2:str value3:str value4:str value5:str):revision1=neyvia.nativeapp.edit(sessionId:sessionId value:value1) C revision1; revision2=neyvia.nativeapp.edit(sessionId:sessionId value:value2) C revision2; revision3=neyvia.nativeapp.edit(sessionId:sessionId value:value3) C revision3; revision4=neyvia.nativeapp.edit(sessionId:sessionId value:value4) C revision4; revision5=neyvia.nativeapp.edit(sessionId:sessionId value:value5) C revision5; persist=neyvia.nativeapp.persist(sessionId:sessionId) C persist -- Revise an owned memo, budget, slide deck, versioned note or browser card; persist and independently verify the artifact
V P revise-save-reopen -> script why:"typed manual runner; stops at every judgement"
X New-process ownership or guard fails -> Refuse the session; never use an existing instance
F Firefox-family screenshot checks validate the rendered color and visible heading ink, not OCR text
F Pixel preview and UIA interaction are separate from these application-native tools
M native-applications "Only host-owned token files and hidden COM instances; compilation never removes native verifiers or guard checks" src:"authored manual" state:verified
-- @proof {"checkedAt":["cua_native_procedures.HostedNativeApplications.request","cua_native_procedures.HostedNativeApplications.__getattr__","cua_native_procedures.NativeApplications.open","cua_native_procedures.NativeApplications.edit","cua_native_procedures.NativeApplications.persist","cua_native_procedures.NativeApplications.observe","cua_native_procedures.NativeApplications.close","cua_native_procedures.NativeApplications.native_process","proofs_applications_journey.self_check"],"claim":"A disposable Unicode Git note is edited, read before save, committed through the owned Git CLI, and independently observed from HEAD; multiline input preserves the saved bytes and a later edit makes the prior saved view stale.","id":"p22.applications.git-note-journey","impact":["Native applications","Owned Git note editing and save/reopen"],"phase":"post"}
