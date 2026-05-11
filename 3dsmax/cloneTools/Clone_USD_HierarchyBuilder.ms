-- Author: Clone.
-- PowerUSD Hierarchy Builder
-- Shared utilities for hierarchy detection and metadata generation.
-- Used by both powerusd.ms (export) and reassemble.ms (dry hierarchy).

global ExportNodeData
global getHierarchyRoot
global getAllDescendants
global getLayerPath
global buildFolderPath
global hasUSDProperties
global findAttributedParent
global findSceneParent
global getAllAncestors
global getDescendantsWithoutAttr
global isInstancableGeometry
global groupByInstances
global selectMasterInstance
global appendUniqueNode
global isCameraNode
global getOwningCameraForTarget
global isCameraTargetNode
global collectCameraBundle
global partitionCamerasToSingleExport
global bundleCameraTargetsInExportSets
global writeHierarchyMetadata
global buildAdvancedExportSets
global findAdvancedExportUnitForObject
global buildAdvancedSingleExportSets
global buildAdvancedSingleSeparateExportSets
global printHierarchyPreview
global writeCameraSequence
global captureViewportThumb
global buildParentFolderPath
global convertGroupsToDummies
global exportMaterialXSidecarForNodes
global exportUsdViaPythonBridge
global performBatchExport
global g_PowerUSD_HierarchyBuilderDir

if (getSourceFileName() != undefined and getSourceFileName() != "") do
	g_PowerUSD_HierarchyBuilderDir = getFilenamePath (getSourceFileName())

struct ExportNodeData
(
	exportName,
	rootNodes,
	moveRoot,
	subFolder,
	parentName  -- For hierarchy reconstruction in Advanced mode
)


fn getHierarchyRoot obj =
(
	local currentObj = obj
	while (currentObj.parent != undefined) do
		currentObj = currentObj.parent
	return currentObj
)

fn getAllDescendants rootNode =
(
	local collection = #(rootNode)
	local idx = 1
	while idx <= collection.count do
	(
		local c = collection[idx]
		join collection c.children
		idx += 1
	)
	return collection
)

fn getLayerPath layerObj =
(
	local path = #()
	local currentLayer = layerObj
	local maxDepth = 20  -- Safety limit
	local depth = 0

	while currentLayer != undefined and depth < maxDepth do
	(
		local layerName = currentLayer.name
		-- Skip default layer "0" and empty names
		if layerName != "0" and layerName != "" and layerName != undefined do
			insertItem layerName path 1

		-- Get parent layer
		local parentLayer = currentLayer.getParent()

		-- Stop if parent is same as current (shouldn't happen, but safety check)
		if parentLayer == currentLayer do parentLayer = undefined

		currentLayer = parentLayer
		depth += 1
	)
	return path
)

fn buildFolderPath layerPath =
(
	if layerPath.count == 0 then return ""
	local result = ""
	for i = 1 to layerPath.count do
	(
		if i > 1 then result += "\\"
		result += layerPath[i]
	)
	return result
)

-- Build folder path from scene hierarchy (non-geometry parent names)
fn buildParentFolderPath obj =
(
	local parts = #()
	local current = findSceneParent obj
	while current != undefined do
	(
		if superClassOf current != GeometryClass do
			insertItem current.name parts 1
		current = findSceneParent current
	)
	buildFolderPath parts
)

-- Check if object has USD Properties modifier
fn hasUSDProperties obj =
(
	for mod in obj.modifiers do
		if mod.name == "USD Properties" do return true
	return false
)

-- Find nearest ancestor with USD Properties
fn findAttributedParent obj =
(
	local current = obj.parent
	while current != undefined do
	(
		if hasUSDProperties current do return current
		current = current.parent
	)
	return undefined
)

-- Find immediate scene parent (group head or actual parent)
fn findSceneParent obj =
(
	if obj.parent != undefined then
	(
		local p = obj.parent
		-- If parent is a group member, get the group head
		while (isGroupMember p) do p = p.parent
		return p
	)
	return undefined
)

-- Get all ancestors up to root (for organizational hierarchy)
fn getAllAncestors obj =
(
	local ancestors = #()
	local current = findSceneParent obj
	while current != undefined do
	(
		append ancestors current
		current = findSceneParent current
	)
	return ancestors
)

-- Get all descendants that DON'T have USD Properties (they stay with parent)
fn getDescendantsWithoutAttr rootNode =
(
	local result = #(rootNode)
	local toProcess = #()
	for c in rootNode.children do append toProcess c

	while toProcess.count > 0 do
	(
		local current = toProcess[1]
		deleteItem toProcess 1

		-- Only include if it doesn't have USD Properties
		if not (hasUSDProperties current) then
		(
			append result current
			for c in current.children do append toProcess c
		)
		-- If it has USD Properties, stop traversing this branch (it exports separately)
	)
	return result
)

-- Check if object is a geometry type that can be instanced
fn isInstancableGeometry obj =
(
	superClassOf obj == GeometryClass and
	obj.baseObject != undefined and
	not (isGroupHead obj) and
	not (isGroupMember obj)
)

-- Group objects by their base object (instance detection)
-- Returns: #( #(master, instance1, instance2...), #(master2, inst...), ... )
fn groupByInstances objects =
(
	local processed = #{}
	local groups = #()

	for i = 1 to objects.count do
	(
		if not processed[i] do
		(
			local obj = objects[i]

			if isInstancableGeometry obj then
			(
				local baseObj = obj.baseObject
				local group = #(obj)
				processed[i] = true

				-- Find all other instances
				for j = (i + 1) to objects.count do
				(
					if not processed[j] do
					(
						local other = objects[j]
						if isInstancableGeometry other and other.baseObject == baseObj do
						(
							append group other
							processed[j] = true
						)
					)
				)

				append groups group
			)
			else
			(
				-- Non-instancable object, treat as single item
				append groups #(obj)
				processed[i] = true
			)
		)
	)

	return groups
)

-- Select the master instance from a group (first one found, or one with USD Properties)
fn selectMasterInstance instanceGroup =
(
	-- Prefer one with USD Properties
	for obj in instanceGroup do
		if hasUSDProperties obj do return obj
	-- Otherwise first one
	return instanceGroup[1]
)

fn appendUniqueNode arr node =
(
	if node != undefined and findItem arr node == 0 do append arr node
	return arr
)

fn isCameraNode node =
(
	if node == undefined then return false
	return ((superClassOf node == camera) or (isKindOf node Camera))
)

fn getOwningCameraForTarget targetNode =
(
	if targetNode == undefined then return undefined
	if targetNode.parent != undefined and isCameraNode targetNode.parent then return targetNode.parent

	for cam in cameras do
	(
		if isProperty cam #target and cam.target == targetNode do return cam
	)
	return undefined
)

fn isCameraTargetNode node =
(
	(isKindOf node TargetObject) and (getOwningCameraForTarget node != undefined)
)

fn collectCameraBundle node cameraNodes =
(
	if isCameraNode node then
	(
		appendUniqueNode cameraNodes node
		if isProperty node #target do appendUniqueNode cameraNodes node.target
		return true
	)

	if isCameraTargetNode node then
	(
		appendUniqueNode cameraNodes node
		appendUniqueNode cameraNodes (getOwningCameraForTarget node)
		return true
	)
	return false
)

-- Camera forcing disabled: keep cameras in their original export sets.
fn partitionCamerasToSingleExport exportSets cameraFileName:"Cameras" =
(
	return exportSets
)

-- Ensure camera targets are never exported as standalone USD files.
-- Targets are always bundled into their owning camera export set.
fn bundleCameraTargetsInExportSets exportSets =
(
	-- First pass: if a set contains a camera, force-include its target.
	for i = 1 to exportSets.count do
	(
		local item = exportSets[i]
		if item.rootNodes == undefined do continue

		for n in item.rootNodes do
		(
			if isCameraNode n and isProperty n #target do appendUniqueNode item.rootNodes n.target
		)
		exportSets[i] = item
	)

	-- Second pass: move any target-only node into the owning camera's set.
	for i = 1 to exportSets.count do
	(
		local item = exportSets[i]
		if item.rootNodes == undefined or item.rootNodes.count == 0 do continue

		local filteredNodes = #()
		local changed = false

		for n in item.rootNodes do
		(
			if isCameraTargetNode n then
			(
				local cam = getOwningCameraForTarget n
				local moved = false

				if cam != undefined then
				(
					local camSetIndex = 0
					for j = 1 to exportSets.count do
					(
						if exportSets[j].rootNodes != undefined and findItem exportSets[j].rootNodes cam > 0 do
						(
							camSetIndex = j
							exit
						)
					)

					-- If no camera set exists yet, create one based on this item's metadata.
					if camSetIndex == 0 then
					(
						append exportSets (ExportNodeData exportName:cam.name rootNodes:#(cam) moveRoot:cam subFolder:item.subFolder parentName:item.parentName)
						camSetIndex = exportSets.count
					)

					local camSet = exportSets[camSetIndex]
					if camSet.rootNodes == undefined do camSet.rootNodes = #()
					appendUniqueNode camSet.rootNodes cam
					appendUniqueNode camSet.rootNodes n
					if isProperty cam #target do appendUniqueNode camSet.rootNodes cam.target
					exportSets[camSetIndex] = camSet

					if camSetIndex != i then
					(
						changed = true
						moved = true
					)
				)

				if not moved do append filteredNodes n
			)
			else
			(
				append filteredNodes n
			)
		)

		if changed do item.rootNodes = filteredNodes
		exportSets[i] = item
	)

	-- Remove empty sets left behind after moving targets.
	for i = exportSets.count to 1 by -1 do
	(
		local item = exportSets[i]
		if item.rootNodes == undefined or item.rootNodes.count == 0 do deleteItem exportSets i
	)

	return exportSets
)


-- Write hierarchy metadata for Assembler as JSON
fn jsonEscapeString s =
(
	local out = s as string
	out = substituteString out "\\" "\\\\"
	out = substituteString out "\"" "\\\""
	out = substituteString out "\r" "\\r"
	out = substituteString out "\n" "\\n"
	out = substituteString out "\t" "\\t"
	out
)

fn pythonEscapeString s =
(
	local out = s as string
	out = substituteString out "\\" "\\\\"
	out = substituteString out "'" "\\'"
	out = substituteString out "\r" "\\r"
	out = substituteString out "\n" "\\n"
	out = substituteString out "\t" "\\t"
	out
)

fn pythonListFromNodeHandles nodes =
(
	local out = "["
	local firstItem = true
	for n in nodes do
	(
		if not isValidNode n do continue
		local handle = try((getHandleByAnim n) as integer)catch(undefined)
		if handle == undefined do continue
		if not firstItem do out += ", "
		out += (handle as string)
		firstItem = false
	)
	out += "]"
	out
)

fn exportUsdViaPythonBridge filePath nodes startFrame endFrame fps forceMaterialXSidecar:false inlineMaterialXIntoUsd:false referenceTextures:true =
(
	local bridgeDir = if g_PowerUSD_HierarchyBuilderDir != undefined and g_PowerUSD_HierarchyBuilderDir != "" then g_PowerUSD_HierarchyBuilderDir else ""
	if bridgeDir == "" and isFunction ::PowerUSD_getScriptsDir do bridgeDir = (::PowerUSD_getScriptsDir() + "cloneTools\\")

	local bridgePath = bridgeDir + "Clone_USD_ExportBridge.py"
	if not doesFileExist bridgePath then
	(
		format "Python USD export FAILED: missing bridge script %\n" bridgePath
		return false
	)

	local nodeHandlesPy = pythonListFromNodeHandles nodes
	if nodeHandlesPy == "[]" then
	(
		format "Python USD export skipped: no valid node handles.\n"
		return false
	)

	local safeFilePath = pythonEscapeString filePath

	global g_PowerUSD_PythonExportOk = false
	global g_PowerUSD_PythonExportError = ""

	python.Execute ("import pymxs; pymxs.runtime._powerusd_export_path = r'" + safeFilePath + "'")
	python.Execute ("import pymxs; pymxs.runtime._powerusd_export_node_handles = " + nodeHandlesPy)
	python.Execute ("import pymxs; pymxs.runtime._powerusd_export_start_frame = " + ((startFrame as integer) as string))
	python.Execute ("import pymxs; pymxs.runtime._powerusd_export_end_frame = " + ((endFrame as integer) as string))
	python.Execute ("import pymxs; pymxs.runtime._powerusd_export_fps = " + ((fps as integer) as string))
	python.Execute ("import pymxs; pymxs.runtime._powerusd_force_materialx_sidecar = " + (if forceMaterialXSidecar then "True" else "False"))
	python.Execute ("import pymxs; pymxs.runtime._powerusd_inline_materialx_into_usd = " + (if inlineMaterialXIntoUsd then "True" else "False"))
	python.Execute ("import pymxs; pymxs.runtime._powerusd_reference_textures = " + (if referenceTextures then "True" else "False"))
	python.Execute "import pymxs; pymxs.runtime.g_PowerUSD_PythonExportOk = False; pymxs.runtime.g_PowerUSD_PythonExportError = ''"

	try
	(
		python.ExecuteFile bridgePath
	)
	catch
	(
		g_PowerUSD_PythonExportError = getCurrentException() as string
	)

	if g_PowerUSD_PythonExportOk != true do
	(
		local errMsg = if g_PowerUSD_PythonExportError != undefined and g_PowerUSD_PythonExportError != "" then g_PowerUSD_PythonExportError else "Unknown Python export error"
		format "Python USD export FAILED: %\n" errMsg
	)

	g_PowerUSD_PythonExportOk == true
)

-- Run the bridge's post-process pipeline (asset wrap + MaterialX sidecar +
-- optional inline) against an already-written USD from the legacy maxUsd
-- exportFile path. Leaves USDs without MaterialX untouched aside from the
-- wrap step — MtlXIOUtil itself fails silently when no MTLX content exists.
fn postprocessUsdViaPythonBridge filePath nodes forceMaterialXSidecar:false inlineMaterialXIntoUsd:false referenceTextures:true =
(
	local bridgeDir = if g_PowerUSD_HierarchyBuilderDir != undefined and g_PowerUSD_HierarchyBuilderDir != "" then g_PowerUSD_HierarchyBuilderDir else ""
	if bridgeDir == "" and isFunction ::PowerUSD_getScriptsDir do bridgeDir = (::PowerUSD_getScriptsDir() + "cloneTools\\")

	local bridgePath = bridgeDir + "Clone_USD_ExportBridge.py"
	if not doesFileExist bridgePath then
	(
		local altBridgePath = (::PowerUSD_getScriptsDir() + "Clone_USD_ExportBridge.py")
		if doesFileExist altBridgePath then bridgePath = altBridgePath
		else
		(
			format "USD postprocess FAILED: missing bridge script %\n" bridgePath
			return false
		)
	)

	local nodeHandlesPy = pythonListFromNodeHandles nodes
	local safeFilePath = pythonEscapeString filePath

	global g_PowerUSD_PythonExportOk = false
	global g_PowerUSD_PythonExportError = ""

	python.Execute ("import pymxs; pymxs.runtime._powerusd_bridge_mode = 'postprocess'")
	python.Execute ("import pymxs; pymxs.runtime._powerusd_export_path = r'" + safeFilePath + "'")
	python.Execute ("import pymxs; pymxs.runtime._powerusd_export_node_handles = " + nodeHandlesPy)
	python.Execute ("import pymxs; pymxs.runtime._powerusd_force_materialx_sidecar = " + (if forceMaterialXSidecar then "True" else "False"))
	python.Execute ("import pymxs; pymxs.runtime._powerusd_inline_materialx_into_usd = " + (if inlineMaterialXIntoUsd then "True" else "False"))
	python.Execute ("import pymxs; pymxs.runtime._powerusd_reference_textures = " + (if referenceTextures then "True" else "False"))
	python.Execute "import pymxs; pymxs.runtime.g_PowerUSD_PythonExportOk = False; pymxs.runtime.g_PowerUSD_PythonExportError = ''"

	try
	(
		python.ExecuteFile bridgePath
	)
	catch
	(
		g_PowerUSD_PythonExportError = getCurrentException() as string
	)

	-- Reset to default so a subsequent bridge call runs full export, not postprocess
	python.Execute "import pymxs; pymxs.runtime._powerusd_bridge_mode = 'export'"

	if g_PowerUSD_PythonExportOk != true do
	(
		local errMsg = if g_PowerUSD_PythonExportError != undefined and g_PowerUSD_PythonExportError != "" then g_PowerUSD_PythonExportError else "Unknown post-process error"
		format "USD postprocess FAILED: %\n" errMsg
	)

	g_PowerUSD_PythonExportOk == true
)

fn writeHierarchyMetadata exportSets outDir =
(
	local metaPath = outDir + "\\_hierarchy.json"
	local f = createFile metaPath

	format "{\n" to:f
	for i = 1 to exportSets.count do
	(
		local item = exportSets[i]
		local parentStr = if item.parentName != undefined then item.parentName else ""
		local subFolderStr = if item.subFolder != undefined then item.subFolder else ""

		-- Keep folders slash-normalized and JSON-safe.
		local safeSubFolder = substituteString subFolderStr "\\" "/"
		local safeName = jsonEscapeString item.exportName
		local parentJson = if parentStr == "" then "null" else ("\"" + (jsonEscapeString parentStr) + "\"")
		local subFolderJson = if safeSubFolder == "" then "null" else ("\"" + (jsonEscapeString safeSubFolder) + "\"")

		format "  \"%\": {\"parent\": %, \"subFolder\": %}" safeName parentJson subFolderJson to:f

		if i < exportSets.count then format ",\n" to:f
		else format "\n" to:f
	)
	format "}\n" to:f

	close f
	format "Wrote hierarchy metadata: %\n" metaPath
)

-- Build Advanced mode export sets (shared by export and dry preview)
fn buildAdvancedExportSets rawSelection outDir writeMetadata:true useLayers:false =
(
	local exportSets = #()
	local processedObjects = #()
	local organizationalNodes = #()

	-- Find all objects with USD Properties in selection
	local attributedObjects = #()
	local hierarchyRoots = #()

	for obj in rawSelection do
	(
		local cameraNode = undefined
		if isKindOf obj Camera then
			cameraNode = obj
		else if (isKindOf obj TargetObject) and obj.parent != undefined and isKindOf obj.parent Camera then
			cameraNode = obj.parent

		if cameraNode != undefined then
		(
			if findItem attributedObjects cameraNode == 0 do append attributedObjects cameraNode
		)
		else
		(
			local root = getHierarchyRoot obj
			if findItem hierarchyRoots root == 0 do append hierarchyRoots root

			-- Only treat root as export unit if it has geometry or USD Properties
			-- Helpers/Dummies/Points without USD Properties are organizational structure
			if hasUSDProperties root or superClassOf root == GeometryClass then
			(
				if findItem attributedObjects root == 0 do append attributedObjects root
			)

			local allDescendants = getAllDescendants root
			for desc in allDescendants do
			(
				if hasUSDProperties desc and findItem attributedObjects desc == 0 do
					append attributedObjects desc
			)
		)
	)

	-- Collect all organizational ancestors (groups/helpers without USD Properties)
	-- Also include hierarchy roots that are helpers (not in attributedObjects)
	for obj in attributedObjects do
	(
		local ancestors = getAllAncestors obj
		for anc in ancestors do
		(
			if findItem organizationalNodes anc == 0 and findItem attributedObjects anc == 0 do
				append organizationalNodes anc
		)
	)

	-- Ensure hierarchy roots that are helpers get added as organizational
	for root in hierarchyRoots do
	(
		if findItem attributedObjects root == 0 and findItem organizationalNodes root == 0 do
			append organizationalNodes root
	)

	for org in organizationalNodes do
	(
		local orgParent = findSceneParent org
		local parentName = if orgParent != undefined then orgParent.name else undefined
		append exportSets (ExportNodeData exportName:org.name rootNodes:#() moveRoot:undefined subFolder:undefined parentName:parentName)
	)

	local instanceGroups = groupByInstances attributedObjects

	-- Process each instance group - export ALL instances together, MaxUSD handles instancing
	for group in instanceGroups do
	(
		local master = selectMasterInstance group

		if findItem processedObjects master == 0 do
		(
			-- Mark all in group as processed
			for obj in group do append processedObjects obj

			local folderPath = if useLayers then buildFolderPath (getLayerPath master.layer) else buildParentFolderPath master

			-- Collect ALL nodes to export: all instances + their descendants without USD Properties
			local nodesToExport = #()
			for obj in group do join nodesToExport (getDescendantsWithoutAttr obj)

			-- Find actual scene parent of master
			local sceneParent = findSceneParent master
			local parentName = if sceneParent != undefined then sceneParent.name else undefined

			append exportSets (ExportNodeData exportName:master.name rootNodes:nodesToExport moveRoot:master subFolder:folderPath parentName:parentName)
		)
	)

	if writeMetadata and exportSets.count > 0 do writeHierarchyMetadata exportSets outDir
	return exportSets
)

-- Find the export unit root that Advanced mode would use for a given object.
-- Rule: nearest ancestor with USD Properties, otherwise the hierarchy root.
fn findAdvancedExportUnitForObject obj =
(
	if isKindOf obj Camera then return obj
	if (isKindOf obj TargetObject) and obj.parent != undefined and isKindOf obj.parent Camera then return obj.parent

	local current = obj
	while current != undefined do
	(
		if hasUSDProperties current do return current
		if current.parent == undefined do return current
		current = current.parent
	)
	return obj
)

-- Build Advanced-mode compatible export sets, but only for selected units.
-- Useful for incremental re-export of selected assets as one USD file.
fn buildAdvancedSingleExportSets rawSelection outDir writeMetadata:false useLayers:false =
(
	local exportSets = #()
	local organizationalNodes = #()

	-- Resolve selected objects to their Advanced export units
	local attributedObjects = #()
	for obj in rawSelection do
	(
		local unitRoot = findAdvancedExportUnitForObject obj
		if unitRoot != undefined and findItem attributedObjects unitRoot == 0 do
			append attributedObjects unitRoot
	)

	if attributedObjects.count == 0 then return exportSets

	-- Collect organizational ancestors for hierarchy metadata compatibility
	for obj in attributedObjects do
	(
		local ancestors = getAllAncestors obj
		for anc in ancestors do
		(
			if findItem organizationalNodes anc == 0 and findItem attributedObjects anc == 0 do
				append organizationalNodes anc
		)
	)
	for org in organizationalNodes do
	(
		local orgParent = findSceneParent org
		local parentName = if orgParent != undefined then orgParent.name else undefined
		append exportSets (ExportNodeData exportName:org.name rootNodes:#() moveRoot:undefined subFolder:undefined parentName:parentName)
	)

	-- Keep the same instance discovery as Advanced mode, but merge every
	-- resolved unit into one export set so Single Export writes one USD file.
	local instanceGroups = groupByInstances attributedObjects
	local nodesToExport = #()
	local moveRoot = undefined
	local exportName = undefined
	local parentName = undefined

	for group in instanceGroups do
	(
		local master = selectMasterInstance group

		if moveRoot == undefined do moveRoot = master
		if exportName == undefined do exportName = master.name

		local sceneParent = findSceneParent master
		if parentName == undefined and sceneParent != undefined do parentName = sceneParent.name

		for obj in group do
		(
			for node in (getDescendantsWithoutAttr obj) do appendUniqueNode nodesToExport node
		)
	)

	if nodesToExport.count > 0 do
	(
		if rawSelection.count > 0 do
		(
			local selectedRoot = findAdvancedExportUnitForObject rawSelection[1]
			if selectedRoot != undefined and selectedRoot.name != undefined and selectedRoot.name != "" do exportName = selectedRoot.name
		)
		append exportSets (ExportNodeData exportName:exportName rootNodes:nodesToExport moveRoot:moveRoot subFolder:undefined parentName:parentName)
	)

	if writeMetadata and exportSets.count > 0 do writeHierarchyMetadata exportSets outDir
	return exportSets
)

-- Build Advanced-mode compatible export sets for selected units, but keep
-- each resolved unit as a separate USD file. This is the old Single Export
-- behavior kept as an explicit option.
fn buildAdvancedSingleSeparateExportSets rawSelection outDir writeMetadata:false useLayers:false =
(
	local exportSets = #()
	local processedObjects = #()
	local organizationalNodes = #()

	local attributedObjects = #()
	for obj in rawSelection do
	(
		local unitRoot = findAdvancedExportUnitForObject obj
		if unitRoot != undefined and findItem attributedObjects unitRoot == 0 do
			append attributedObjects unitRoot
	)

	if attributedObjects.count == 0 then return exportSets

	for obj in attributedObjects do
	(
		local ancestors = getAllAncestors obj
		for anc in ancestors do
		(
			if findItem organizationalNodes anc == 0 and findItem attributedObjects anc == 0 do
				append organizationalNodes anc
		)
	)
	for org in organizationalNodes do
	(
		local orgParent = findSceneParent org
		local parentName = if orgParent != undefined then orgParent.name else undefined
		append exportSets (ExportNodeData exportName:org.name rootNodes:#() moveRoot:undefined subFolder:undefined parentName:parentName)
	)

	local instanceGroups = groupByInstances attributedObjects
	for group in instanceGroups do
	(
		local master = selectMasterInstance group
		if findItem processedObjects master == 0 do
		(
			for obj in group do append processedObjects obj

			local folderPath = if useLayers then buildFolderPath (getLayerPath master.layer) else buildParentFolderPath master

			local nodesToExport = #()
			for obj in group do join nodesToExport (getDescendantsWithoutAttr obj)

			local sceneParent = findSceneParent master
			local parentName = if sceneParent != undefined then sceneParent.name else undefined

			append exportSets (ExportNodeData exportName:master.name rootNodes:nodesToExport moveRoot:master subFolder:folderPath parentName:parentName)
		)
	)

	if writeMetadata and exportSets.count > 0 do writeHierarchyMetadata exportSets outDir
	return exportSets
)

-- Dry preview for _hierarchy.json entries without running exporter
fn printHierarchyPreview exportSets =
(
	format "\n=== ASSEMBLER _hierarchy PREVIEW ===\n"
	if exportSets.count == 0 then
	(
		format "(no entries)\n"
		format "=== END ASSEMBLER PREVIEW ===\n\n"
		return false
	)

	for item in exportSets do
	(
		local parentStr = if item.parentName != undefined then item.parentName else "(root)"
		format "  % -> %\n" item.exportName parentStr
	)

	format "=== END ASSEMBLER PREVIEW (% entries) ===\n\n" exportSets.count
	return true
)

-- Write camera sequence JSON from State Sets (for Unreal Camera Cut Track)
fn writeCameraSequence outDir =
(
	try
	(
		local ssPlug = (dotNetClass "Autodesk.Max.StateSets.Plugin").Instance
		if ssPlug == undefined do (format "State Sets plugin not available, skipping camera sequence.\n"; return false)

		local ssRoot = ssPlug.EntityManager.RootEntity
		if ssRoot == undefined do return false

		local ssMaster = undefined
		for i = 0 to ssRoot.Children.Count - 1 do
		(
			local child = ssRoot.Children.Item[i]
			if (child.GetType()).Name == "Master" do (ssMaster = child; exit)
		)
		if ssMaster == undefined do return false

		local tpf = ticksPerFrame
		local camEntries = #()
		local ssKids = ssMaster.Children

		for idx = 0 to ssKids.Count - 1 do
		(
			local ssItem = ssKids.Item[idx]
			local camName = ""
			try (
				local cam = ssItem.ActiveViewportCamera
				if cam != undefined do camName = cam.Name
			) catch ()

			if camName != "" do
			(
				local sf = 0
				local ef = 0
				try (
					local rr = ssItem.RenderRange
					if rr != undefined do (sf = rr.Start / tpf; ef = rr.End / tpf)
				) catch ()
				append camEntries #(sf, ef, camName)
			)
		)

		if camEntries.count == 0 do (format "No camera State Sets found, skipping camera sequence.\n"; return false)

		-- Sort by start frame
		for i = 1 to camEntries.count do
			for j = 1 to camEntries.count - i do
				if camEntries[j][1] > camEntries[j+1][1] do
				(
					local temp = camEntries[j]
					camEntries[j] = camEntries[j+1]
					camEntries[j+1] = temp
				)

		local metaPath = outDir + "\\_camera_sequence.json"
		local f = createFile metaPath

		format "{\n" to:f
		format "  \"fps\": %,\n" (frameRate as integer) to:f
		format "  \"sequence\": [\n" to:f
		for i = 1 to camEntries.count do
		(
			local entry = camEntries[i]
			format "    {\"camera\": \"%\", \"startFrame\": %, \"endFrame\": %}" entry[3] entry[1] entry[2] to:f
			if i < camEntries.count then format ",\n" to:f
			else format "\n" to:f
		)
		format "  ]\n" to:f
		format "}\n" to:f

		close f
		format "Wrote camera sequence: %\n" metaPath
		return true
	)
	catch
	(
		format "Error writing camera sequence: %\n" (getCurrentException())
		return false
	)
)

-- Capture a viewport thumbnail for the given nodes
fn captureViewportThumb nodes filePath thumbSize:256 =
(
	local oldRenderer = renderers.current
	local oldBgColor = backgroundColor
	local oldUseEnvMap = useEnvironmentMap

	local nodeSet = for n in nodes collect n
	local hiddenObjs = for o in objects where not o.isHidden and findItem nodeSet o == 0 collect o
	hide hiddenObjs

	select nodes
	max zoomext sel

	renderers.current = Quicksilver_Hardware_Renderer()
	backgroundColor = color 0 0 0 0
	useEnvironmentMap = false

	local thumb = render outputSize:[thumbSize, thumbSize] vfb:off quiet:true

	pngio.setAlpha true
	thumb.filename = filePath
	save thumb
	close thumb

	renderers.current = oldRenderer
	backgroundColor = oldBgColor
	useEnvironmentMap = oldUseEnvMap

	unhide hiddenObjs
	return true
)

fn exportMaterialXSidecarForNodes nodes usdFilePath =
(
	if usdFilePath == undefined or usdFilePath == "" then return false

	try (
		if MtlXIOUtil == undefined then
		(
			format "MaterialX sidecar skipped: MtlXIOUtil unavailable.\n"
			return false
		)
	) catch (
		format "MaterialX sidecar skipped: MtlXIOUtil unavailable.\n"
		return false
	)

	local materials = #()
	local seenKeys = #()

	for n in nodes do
	(
		if not isValidNode n do continue
		local m = try(n.material)catch(undefined)
		if m == undefined do continue

		local key = try((getHandleByAnim m) as string)catch("")
		if key == "" do key = try((m.name as string) + "|" + ((classof m) as string))catch((m as string))

		if findItem seenKeys key == 0 do
		(
			append seenKeys key
			append materials m
		)
	)

	if materials.count == 0 then
	(
		format "MaterialX sidecar skipped: no materials on exported nodes.\n"
		return false
	)

	local sidecarPath = (getFilenamePath usdFilePath) + (getFilenameFile usdFilePath) + ".mtlx"

	try
	(
		MtlXIOUtil.SetDefaults()
		if isProperty MtlXIOUtil #CopyTexturesToSaveLocation do MtlXIOUtil.CopyTexturesToSaveLocation = true
		if isProperty MtlXIOUtil #UseRelativePaths do MtlXIOUtil.UseRelativePaths = true
		if isProperty MtlXIOUtil #ResolveTexturePaths do MtlXIOUtil.ResolveTexturePaths = true

		local ok = MtlXIOUtil.ExportMtlX sidecarPath materials
		if ok then
		(
			format "MaterialX sidecar written: %\n" sidecarPath
			true
		)
		else
		(
			format "MaterialX sidecar FAILED: %\n" (try(MtlXIOUtil.GetError())catch("Unknown error"))
			false
		)
	)
	catch
	(
		format "MaterialX sidecar FAILED: %\n" (getCurrentException())
		false
	)
)

-- Permanently convert Max groups to plain Dummy helpers in the given selection.
-- Must be called BEFORE buildAdvancedExportSets so the export sets see plain Dummies.
-- Group heads cause double-wrapping under Xforms in MaxUSD.
-- Deletes each group head and replaces it with a plain Dummy that keeps the
-- same name, transform, parent, children, and modifiers (e.g. USD Properties).
fn convertGroupsToDummies nodeArray =
(
	-- Walk selection + ancestors + descendants to find every group head
	local groupHeads = #()
	for n in nodeArray do
	(
		-- Walk up
		local current = n
		while current != undefined do
		(
			if isGroupHead current and findItem groupHeads current == 0 do
				append groupHeads current
			current = current.parent
		)
		-- Walk down
		if isGroupHead n do
		(
			local desc = getAllDescendants n
			for d in desc do
				if isGroupHead d and findItem groupHeads d == 0 do
					append groupHeads d
		)
	)

	if groupHeads.count == 0 do return true

	-- Sort by depth (deepest first) so innermost groups are converted first
	local depths = for g in groupHeads collect
	(
		local d = 0
		local p = g.parent
		while p != undefined do (d += 1; p = p.parent)
		d
	)
	for i = 1 to groupHeads.count do
		for j = 1 to groupHeads.count - i do
			if depths[j] < depths[j+1] do
			(
				local tg = groupHeads[j]; groupHeads[j] = groupHeads[j+1]; groupHeads[j+1] = tg
				local td = depths[j]; depths[j] = depths[j+1]; depths[j+1] = td
			)

	for grp in groupHeads do
	(
		if not isValidNode grp do continue

		local grpName = grp.name
		local grpTransform = grp.transform
		local grpParent = grp.parent
		local grpIsHidden = grp.isHidden

		-- Open group and collect children
		setGroupOpen grp true
		local members = for c in grp.children collect c

		-- Closed groups put modifiers on MEMBERS, not the head.
		-- Read USD Properties values from the first member that has it, then strip from all.
		local usdPropValues = undefined
		for m in members do
		(
			for modIdx = m.modifiers.count to 1 by -1 do
			(
				local mod = m.modifiers[modIdx]
				if mod.name == "USD Properties" do
				(
					if usdPropValues == undefined do
					(
						usdPropValues = #(
							mod.USD_GeomType, mod.USD_Kind, mod.USD_Purpose,
							mod.USD_Instanceable, mod.USD_Hidden, mod.USD_Active,
							mod.USD_AssetVersion, mod.USD_DrawMode, mod.USD_Payload
						)
					)
					deleteModifier m modIdx
				)
			)
		)
		-- Also check the group head itself
		if usdPropValues == undefined do
		(
			for mod in grp.modifiers where mod.name == "USD Properties" do
			(
				usdPropValues = #(
					mod.USD_GeomType, mod.USD_Kind, mod.USD_Purpose,
					mod.USD_Instanceable, mod.USD_Hidden, mod.USD_Active,
					mod.USD_AssetVersion, mod.USD_DrawMode, mod.USD_Payload
				)
			)
		)

		-- Copy transform controller (preserves keyframes/animation)
		local grpTMController = copy grp.transform.controller

		-- Strip group member flags so children can be freely reparented
		for m in members do setGroupMember m false

		-- Park children temporarily
		for m in members do
			if isValidNode m do m.parent = grpParent

		-- Nuke the group head
		setGroupHead grp false
		delete grp

		-- Create a brand-new plain Dummy and restore animation
		local newDummy = Dummy name:grpName isHidden:grpIsHidden
		newDummy.transform.controller = grpTMController
		if grpParent != undefined and isValidNode grpParent do newDummy.parent = grpParent

		-- Re-create USD Properties properly (EmptyModifier + USDPropertiesCA custAttributes)
		if usdPropValues != undefined and ::USDPropertiesCA != undefined do
		(
			local newMod = EmptyModifier name:"USD Properties"
			addModifier newDummy newMod
			custAttributes.add newMod ::USDPropertiesCA
			newMod.USD_GeomType     = usdPropValues[1]
			newMod.USD_Kind         = usdPropValues[2]
			newMod.USD_Purpose      = usdPropValues[3]
			newMod.USD_Instanceable = usdPropValues[4]
			newMod.USD_Hidden       = usdPropValues[5]
			newMod.USD_Active       = usdPropValues[6]
			newMod.USD_AssetVersion = usdPropValues[7]
			newMod.USD_DrawMode     = usdPropValues[8]
			newMod.USD_Payload      = usdPropValues[9]
		)

		-- Reparent former members under the new Dummy
		for m in members do
			if isValidNode m do m.parent = newDummy

		-- Add new dummy to selection (replacing deleted group head)
		selectMore newDummy

		format "  converted group '%' -> Dummy (% children)\n" grpName members.count
	)
)

-- Batch export a list of ExportNodeData sets to USD files
fn performBatchExport exportSets outDir useOrigin useThumbnails startFrame endFrame fps useLegacyExport:false forceMaterialXSidecar:false inlineMaterialXIntoUsd:false referenceTextures:true =
(
	if exportSets.count > 0 then
	(
		local abortBatch = false

		undo "Batch USD Export" on
		(
			with redraw off
			(
				for i = 1 to exportSets.count do
				(
					if not abortBatch do
					(
						local item = exportSets[i]
						if item.rootNodes == undefined or item.rootNodes.count == 0 then
						(
							continue
						)

						local exportDir = outDir
						if item.subFolder != undefined and item.subFolder != "" then
						(
							exportDir = outDir + "\\" + item.subFolder
							makeDir exportDir all:true
						)

						local filePath = exportDir + "\\" + item.exportName + ".usd"
						local thumbPath = exportDir + "\\" + item.exportName + "_thumb.png"
						local originalPos = [0, 0, 0]
						local moved = false

						select item.rootNodes

						try
						(
							if useOrigin and item.moveRoot != undefined then
							(
								originalPos = item.moveRoot.pos
								item.moveRoot.pos = [0, 0, 0]
								moved = true
							)

							local result = false
							if useLegacyExport then
							(
								if i == 1 then
								(
									result = exportFile filePath selectedOnly:true
									if result == false do abortBatch = true
								)
								else
								(
									result = exportFile filePath #noPrompt selectedOnly:true
								)

								-- Legacy exportFile produces the USD but can't wrap assets
								-- or emit MaterialX. Run the bridge's post-process pipeline
								-- against the written file only if the caller actually
								-- asked for wrap/MaterialX work — otherwise leave the
								-- Unreal-tuned legacy output untouched.
								if result != false and (forceMaterialXSidecar or inlineMaterialXIntoUsd) do
								(
									postprocessUsdViaPythonBridge filePath item.rootNodes forceMaterialXSidecar:forceMaterialXSidecar inlineMaterialXIntoUsd:inlineMaterialXIntoUsd referenceTextures:referenceTextures
								)
							)
							else
							(
								result = exportUsdViaPythonBridge filePath item.rootNodes startFrame endFrame fps forceMaterialXSidecar:forceMaterialXSidecar inlineMaterialXIntoUsd:inlineMaterialXIntoUsd referenceTextures:referenceTextures
								if result == false and i == 1 do abortBatch = true
							)

							if useThumbnails and result != false do
							(
								local lowerName = toLower item.exportName
								local skipThumb = (matchPattern lowerName pattern:"*_proxy*") or (matchPattern lowerName pattern:"*_guide*")
								if not skipThumb do
									captureViewportThumb item.rootNodes thumbPath
							)
						)
						catch
						(
							format "Error exporting '%': %\n" item.exportName (getCurrentException())
						)
						finally
						(
							if moved do item.moveRoot.pos = originalPos
						)
					)
				)
			)
		)

		return (not abortBatch)
	)
	return false
)
