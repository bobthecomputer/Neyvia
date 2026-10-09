-- Install the generated script as a LOCAL Studio plugin. No arbitrary code execution.
local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")
local Selection = game:GetService("Selection")
local LogService = game:GetService("LogService")
local ScriptEditorService = game:GetService("ScriptEditorService")
local ChangeHistoryService = game:GetService("ChangeHistoryService")
local hasStudioTests, StudioTestService = pcall(function() return game:GetService("StudioTestService") end)
local playActive, playResult = false, nil
local config = HttpService:JSONDecode([==[__NEYVIA_CONFIG_JSON__]==])
local port = tonumber(string.match(config.httpUrl, "^http://127%.0%.0%.1:(%d+)$"))
assert(port and port >= 1024 and port <= 65535 and port ~= 47881, "Neyvia bridge requires a private literal loopback port")
assert(type(config.token) == "string" and #config.token > 0, "Missing project bridge token")
assert(type(config.projectPath) == "string" and #config.projectPath > 0, "Missing project affinity")
local studioId = HttpService:GenerateGUID(false)
local sessionId, registeredContext
local active = true
local console = {}
local completion
local logConnection = LogService.MessageOut:Connect(function(message, kind)
    table.insert(console, {message = string.sub(message, 1, 4000), kind = tostring(kind)})
    if #console > 200 then table.remove(console, 1) end
end)
plugin.Unloading:Connect(function() active = false; logConnection:Disconnect() end)

local function context()
    if RunService:IsEdit() then return "Edit" end
    if RunService:IsServer() then return "Server" end
    if RunService:IsClient() then return "Client" end
    error("Studio data model context is unavailable")
end
local function post(endpoint, data)
    local response = HttpService:RequestAsync({
        Url = config.httpUrl .. "/api/gamedev/bridge/" .. endpoint,
        Method = "POST",
        Headers = { ["Content-Type"] = "application/json", ["Authorization"] = "Bearer " .. config.token },
        Body = HttpService:JSONEncode(data),
    })
    if not response.Success then error("Bridge HTTP " .. tostring(response.StatusCode)) end
    local body = HttpService:JSONDecode(response.Body)
    if body.ok ~= true then error("Bridge rejected request") end
    return body.data
end
local function objectAt(path)
    assert(type(path) == "string", "path must be a slash-separated Instance path")
    if path == "" or path == "game" then return game end
    local object = game
    for name in string.gmatch(path, "[^/]+") do
        if name ~= "game" then
            local found
            for _, child in ipairs(object:GetChildren()) do
                if child.Name == name then
                    assert(found == nil, "Ambiguous Instance path: " .. name)
                    found = child
                end
            end
            assert(found, "Instance missing: " .. name)
            object = found
        end
    end
    return object
end
local function objectPath(object)
    if object == game then return "game" end
    return objectPath(object.Parent) .. "/" .. object.Name
end
local function observe(object, depth, budget)
    local result = {path = objectPath(object), name = object.Name, className = object.ClassName}
    if object:IsA("BasePart") then
        result.position = {object.Position.X, object.Position.Y, object.Position.Z}
        result.size = {object.Size.X, object.Size.Y, object.Size.Z}
        result.anchored = object.Anchored
    end
    if object:IsA("LuaSourceContainer") then result.source = ScriptEditorService:GetEditorSource(object) end
    result.children = {}
    if depth > 0 then
        for _, child in ipairs(object:GetChildren()) do
            if budget.remaining <= 0 then result.truncated = true; break end
            budget.remaining -= 1
            table.insert(result.children, observe(child, depth - 1, budget))
        end
    end
    return result
end
local function typedValue(value)
    if type(value) ~= "table" then
        assert(type(value) == "string" or type(value) == "number" or type(value) == "boolean", "Unsupported property value")
        return value
    end
    if value.type == "Vector3" then return Vector3.new(value.x, value.y, value.z) end
    if value.type == "Color3" then return Color3.new(value.r, value.g, value.b) end
    if value.type == "CFrame" then return CFrame.new(value.x, value.y, value.z) end
    error("Only Vector3, Color3 and translation CFrame values are supported")
end
local properties = {
    Name = true, Anchored = true, CanCollide = true, Transparency = true,
    Position = true, Size = true, Color = true, CFrame = true, Value = true,
    WalkSpeed = true, JumpPower = true, Enabled = true,
}
local function execute(request)
    local args = request.args or {}
    assert(registeredContext == context(), "Studio context changed; choose the newly registered session")
    if args.context then assert(args.context == context(), "Wrong Edit/Client/Server affinity") end
    if request.action == "transcribe" then
        local nodes = {}
        local descendants = workspace:GetDescendants()
        for i, object in ipairs(descendants) do
            if i > 2000 then break end
            -- Same Scene facts as the Godot/Unity observers so the shared predicates apply:
            -- colliderCount (self or descendant collidable parts), brokenReferences
            -- (required ObjectValue without Value, MeshPart without MeshId), Model scale.
            local attributes = {requiresCollider = object:GetAttribute("laya_requires_collider") == true}
            local measurements = {brokenReferences = 0, colliderCount = 0}
            if object:IsA("ObjectValue") and object:GetAttribute("laya_required_reference") == true then
                measurements.brokenReferences = object.Value == nil and 1 or 0
            end
            if object:IsA("MeshPart") and object.MeshId == "" then
                measurements.brokenReferences += 1
            end
            if object:IsA("BasePart") then
                attributes.size = {object.Size.X, object.Size.Y, object.Size.Z}
                measurements.colliderCount = object.CanCollide and 1 or 0
                attributes.material = tostring(object.Material)
            elseif object:IsA("Model") then
                local scale = object:GetScale()
                attributes.scale = {scale, scale, scale}
                measurements.scaleError = math.abs(scale - 1)
                for _, part in ipairs(object:GetDescendants()) do
                    if part:IsA("BasePart") and part.CanCollide then measurements.colliderCount += 1 end
                end
            end
            table.insert(nodes, {id=objectPath(object),kind=object.ClassName,certainty="observed",attributes=attributes,
                measurements=measurements,relations={parent=objectPath(object.Parent)}})
        end
        return {schema="neyvia.scene.v1",domain="roblox",surface="native-studio",nodes=nodes,truncated=#descendants>2000}
    end
    if request.action == "inspect" then
        return {context = context(), studio_id = studioId, placeId = game.PlaceId,
            running = RunService:IsRunning(), playLaunchActive = playActive, playResult = playResult,
            hierarchy = observe(objectAt(args.path or "game"), math.clamp(args.depth or 2, 0, 8), {remaining = 1000})}
    elseif request.action == "select" then
        local object = objectAt(args.path)
        assert(object ~= game, "Select an Instance below game")
        Selection:Set({object})
        return {path = objectPath(object), selected = true}
    elseif request.action == "console" then
        return {context = context(), entries = console}
    elseif request.action == "edit" then
        assert(context() == "Edit", "Durable edits require the Edit data model")
        local object = objectAt(args.path)
        assert(object ~= game, "Cannot edit the DataModel")
        if args.source ~= nil then
            assert(object:IsA("LuaSourceContainer"), "Source edits require a script")
            assert(type(args.source) == "string" and #args.source <= 1048576, "Source must be at most 1 MB")
            assert(type(args.expectedSource) == "string", "expectedSource required to preserve user changes")
            local changed = false
            ScriptEditorService:UpdateSourceAsync(object, function(old)
                if old ~= args.expectedSource then return nil end
                changed = true
                return args.source
            end)
            assert(changed and ScriptEditorService:GetEditorSource(object) == args.source, "Script changed concurrently; edit refused")
        else
            assert(properties[args.property], "Property not in typed edit allow-list")
            ChangeHistoryService:SetWaypoint("Before Neyvia edit")
            object[args.property] = typedValue(args.value)
            ChangeHistoryService:SetWaypoint("Neyvia edit")
        end
        return {path = objectPath(object), edited = true, context = context()}
    elseif request.action == "run" then
        assert(context() == "Edit", "Launch requires Edit context")
        if args.mode == "play" then
            assert(hasStudioTests, "This Studio version lacks StudioTestService; use native player controls")
            assert(not playActive and StudioTestService.EditModeActive, "A native play test is already active")
            playActive, playResult = true, nil
            task.spawn(function()
                local ok, value = pcall(function() return StudioTestService:ExecutePlayModeAsync(args.testArgs) end)
                playResult = {succeeded = ok, value = ok and value or nil, error = not ok and tostring(value) or nil}
                playActive = false
            end)
            local deadline = os.clock() + 5
            while playActive and StudioTestService.EditModeActive and os.clock() < deadline do task.wait(0.05) end
            assert(not StudioTestService.EditModeActive, playResult and playResult.error or "Native player session did not become active")
            return {mode = "play", testActive = true, launchRequested = true,
                note = "Observe exact Client/Server sessions; end play with stop mode play on the Server session"}
        end
        assert(args.mode == "simulation", "mode must be play or simulation")
        RunService:Run()
        assert(RunService:IsRunning(), "Studio did not start simulation")
        return {running = true, mode = "simulation", context = context()}
    elseif request.action == "stop" then
        if args.mode == "play" then
            assert(hasStudioTests and context() == "Server", "End play requires StudioTestService in the exact Server data model")
            StudioTestService:EndTest(args.result)
            return {endTestRequested = true, context = "Server", note = "Observe Edit session playResult and inactive test before claiming stopped"}
        end
        assert(args.preserveChanges == true, "RunService.Stop preserves simulation changes; use Studio Stop button for restoration, or explicitly set preserveChanges=true")
        RunService:Stop()
        assert(not RunService:IsRunning(), "Studio did not stop simulation")
        return {running = false, context = context(), simulationChangesPreserved = true}
    end
    error("Unsupported action: " .. tostring(request.action))
end
-- RequestAsync yields inside this task; it never blocks Studio's UI thread.
task.spawn(function()
    while active do
        local ok, failure = pcall(function()
            -- Finish the old-context receipt before registering the new context.
            if completion then
                post("complete", completion)
                completion = nil
            end
            local currentContext = context()
            if not sessionId or registeredContext ~= currentContext then
                local capabilities = {"inspect", "transcribe", "select", "console"}
                if currentContext == "Edit" then table.insert(capabilities, "edit"); table.insert(capabilities, "run") end
                table.insert(capabilities, "stop")
                local data = post("register", {engine = "roblox", projectPath = config.projectPath,
                    studio_id = studioId, context = currentContext, capabilities = capabilities})
                assert(data and data.sessionId, "Bridge session missing")
                sessionId = data.sessionId
                registeredContext = currentContext
            end
            local data = post("poll", {sessionId = sessionId})
            if data and data.request then
                local request = data.request
                local succeeded, result = pcall(execute, request)
                completion = {sessionId = sessionId, requestId = request.requestId,
                    status = succeeded and "succeeded" or "failed", result = succeeded and result or {},
                    error = not succeeded and tostring(result) or nil}
            end
        end)
        if not ok then
            -- Do not repeat actions when completion delivery fails.
            if not completion then sessionId = nil end
            warn("Neyvia bridge: " .. tostring(failure))
        end
        task.wait(ok and 0.5 or 3)
    end
end)
