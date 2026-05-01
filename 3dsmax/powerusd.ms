-- Author: Clone.

global g_CloneTools_ScriptsDir

fn CloneTools_uniqueAppend arr value =
(
	if value == undefined or value == "" do return arr
	local v = value as string
	for e in arr where (toLower (e as string)) == (toLower v) do return arr
	append arr v
	arr
)

fn CloneTools_isWritableDir dirPath =
(
	if dirPath == undefined or dirPath == "" do return false
	try (
		makeDir dirPath
		local probe = dirPath + "\\_clonetools_write_test.tmp"
		local f = createFile probe
		close f
		deleteFile probe
		true
	) catch (false)
)

fn CloneTools_detectSourceDir selfFileName =
(
	local candidates = #()
	if ::g_CloneTools_ScriptsDir != undefined and ::g_CloneTools_ScriptsDir != "" do
		CloneTools_uniqueAppend candidates ::g_CloneTools_ScriptsDir

	local pA = try(getSourceFileName())catch("")
	if pA != undefined and pA != "" do CloneTools_uniqueAppend candidates (getFilenamePath pA)

	local pB = try(sourceFileName)catch("")
	if pB != undefined and pB != "" do CloneTools_uniqueAppend candidates (getFilenamePath pB)

	local pC = try(sysInfo.currentdir)catch("")
	if pC != undefined and pC != "" do CloneTools_uniqueAppend candidates pC

	CloneTools_uniqueAppend candidates ((getDir #userScripts) + "\\CloneTools\\")

	for dir in candidates do (
		local direct = dir + selfFileName
		local fromChasers = dir + "cloneTools\\" + selfFileName
		if doesFileExist direct do return dir
		if doesFileExist fromChasers do return (dir + "cloneTools\\")
	)
	undefined
)

fn CloneTools_findSourceFile sourceDir fileName =
(
	local p1 = sourceDir + fileName
	if doesFileExist p1 do return p1
	local p2 = sourceDir + "cloneTools\\" + fileName
	if doesFileExist p2 do return p2
	""
)

fn CloneTools_copyFile sourcePath destPath =
(
	if sourcePath == undefined or sourcePath == "" do return false
	if destPath == undefined or destPath == "" do return false
	if not doesFileExist sourcePath do return false

	if (toLower sourcePath) == (toLower destPath) do return true
	if doesFileExist destPath do deleteFile destPath
	copyFile sourcePath destPath
)

fn CloneTools_installFiles selfFileName extraFiles:#() =
(
	local sourceDir = CloneTools_detectSourceDir selfFileName
	if sourceDir == undefined or sourceDir == "" do return false

	local targetDir = (getDir #userScripts) + "\\CloneTools\\"
	try(makeDir targetDir)catch()

	local files = #()
	append files selfFileName
	for f in extraFiles do append files f

	local copiedSelf = false
	for f in files do (
		local src = CloneTools_findSourceFile sourceDir f
		if src != "" then (
			local dst = targetDir + f
			if CloneTools_copyFile src dst and (toLower f) == (toLower selfFileName) do copiedSelf = true
		)
	)

	if copiedSelf do ::g_CloneTools_ScriptsDir = targetDir
	copiedSelf
)

fn CloneTools_collectMacroPaths selfFileName =
(
	local paths = #()
	local sourceDir = CloneTools_detectSourceDir selfFileName
	if sourceDir != undefined and sourceDir != "" do CloneTools_uniqueAppend paths (sourceDir + selfFileName)
	CloneTools_uniqueAppend paths ((getDir #userScripts) + "\\CloneTools\\" + selfFileName)
	paths
)

fn CloneTools_collectStartupDirs =
(
	local dirs = #()
	local d1 = try(getDir #userStartupScripts)catch("")
	if d1 != undefined and d1 != "" do CloneTools_uniqueAppend dirs d1
	CloneTools_uniqueAppend dirs ((getDir #userScripts) + "\\startup")
	local d2 = try(getDir #startupScripts)catch("")
	if d2 != undefined and d2 != "" do CloneTools_uniqueAppend dirs d2
	dirs
)

fn CloneTools_escapePath path = (substituteString path "\\" "\\\\")

fn CloneTools_installUserMacroMirror selfFileName mirrorName =
(
	local sourceDir = CloneTools_detectSourceDir selfFileName
	if sourceDir == undefined or sourceDir == "" do return false
	local sourceFile = CloneTools_findSourceFile sourceDir selfFileName
	if sourceFile == "" do return false

	local userMacrosDir = getDir #userMacros
	if userMacrosDir == undefined or userMacrosDir == "" do return false
	if not CloneTools_isWritableDir userMacrosDir do return false

	local mirrorPath = userMacrosDir + "\\" + mirrorName
	if doesFileExist mirrorPath do deleteFile mirrorPath
	CloneTools_copyFile sourceFile mirrorPath
)

fn PowerUSD_getScriptsDir =
(
	-- The install layout places every Clone_USD_* helper flat under
	-- <userScripts>\CloneTools\. The repo keeps them beside this script in
	-- 3dsmax\cloneTools\. Probe candidates in order of preference and return
	-- whichever one actually contains Clone_USD_HierarchyBuilder.ms (the
	-- canonical dependency). Falls back to the install path unconditionally.
	local sentinel = "Clone_USD_HierarchyBuilder.ms"
	local candidates = #()
	if ::g_CloneTools_ScriptsDir != undefined and ::g_CloneTools_ScriptsDir != "" do
	(
		append candidates ::g_CloneTools_ScriptsDir
		append candidates (::g_CloneTools_ScriptsDir + "cloneTools\\")
		append candidates (::g_CloneTools_ScriptsDir + "cloneTools/")
	)
	append candidates ((getDir #userScripts) + "\\CloneTools\\")

	local chosen = undefined
	for c in candidates while chosen == undefined do
		if doesFileExist (c + sentinel) do chosen = c

	if chosen == undefined then ((getDir #userScripts) + "\\CloneTools\\")
	else chosen
)

fn PowerUSD_resolveToolPath fileName =
(
	local baseDir = PowerUSD_getScriptsDir()
	local p1 = baseDir + fileName
	if doesFileExist p1 do return p1

	local p2 = baseDir + "cloneTools\\" + fileName
	if doesFileExist p2 do return p2

	undefined
)

fn PowerUSD_tryLoadMS fileName required:true =
(
	local p = PowerUSD_resolveToolPath fileName
	if p == undefined then (
		if required do messageBox ("Missing file:\n" + fileName + "\n\nLooked in:\n" + (PowerUSD_getScriptsDir()) + "\n" + (PowerUSD_getScriptsDir()) + "cloneTools\\") title:"PowerUSD Error"
		return false
	)

	try (
		fileIn p
		true
	) catch (
		if required do messageBox ("Failed to load:\n" + p + "\n\n" + (getCurrentException() as string)) title:"PowerUSD Error"
		false
	)
)

fn PowerUSD_tryRunPy fileName =
(
	local p = PowerUSD_resolveToolPath fileName
	if p != undefined do (
		try(python.ExecuteFile p)catch(format "[PowerUSD] Failed python file: %\n" p)
	)
)

fn PowerUSD_InstallStartupLoader =
(
	local selfFile = "powerusd.ms"
	local deps = #(
		"Clone_USD_HierarchyBuilder.ms",
		"Clone_USD_CleanStruct.py",
		"Clone_USD_usdWrapper.py",
		"Clone_USD_PropertiesChaser.py",
		"Clone_USD_StageAssembler.py",
		"Clone_USD_AttributeDef.ms"
	)
	CloneTools_installFiles selfFile extraFiles:deps
	CloneTools_installUserMacroMirror selfFile "PowerUSDExport_CloneTools.mcr"

	local macroPaths = CloneTools_collectMacroPaths selfFile
	local macroList = ""
	for i = 1 to macroPaths.count do (
		local comma = if i < macroPaths.count then "," else ""
		macroList += ("\t\t\"" + (CloneTools_escapePath macroPaths[i]) + "\"" + comma + "\n")
	)

	local loaderScript =
		"-- Auto-generated by PowerUSD\n" +
		"(\n" +
		"\tlocal macroPaths = #(\n" +
		macroList +
		"\t)\n" +
		"\tfor p in macroPaths do (\n" +
		"\t\tif doesFileExist p do (\n" +
		"\t\t\tfileIn p quiet:true\n" +
		"\t\t\texit\n" +
		"\t\t)\n" +
		"\t)\n" +
		")\n"

	local installCount = 0
	for startupDir in CloneTools_collectStartupDirs() do (
		if CloneTools_isWritableDir startupDir then (
			local loaderPath = startupDir + "\\PowerUSD_LoadMacros.ms"
			try (
				local f = createFile loaderPath
				format "%" loaderScript to:f
				close f
				installCount += 1
			) catch ()
		)
	)

	installCount > 0
)

macroScript PowerUSDExport
category:"CloneTools"
toolTip:"Advanced USD Export with Hierarchy & Assembler"
buttonText:"Clone PowerUSD UI"
(
	persistent global g_PowerUSD_lastDir

	fn setAssemblerPythonVars outDir defaultPrimName startFrame endFrame fps inlineCameras:true =
	(
		local safeOutDir = substituteString outDir "'" "\\'"
		python.Execute ("_powerusd_export_dir = r'" + safeOutDir + "'")

		local primName = ""
		if defaultPrimName != undefined do primName = trimRight (trimLeft defaultPrimName)
		if primName != "" then
		(
			local safePrim = substituteString primName "'" "\\'"
			python.Execute ("_powerusd_default_prim = r'" + safePrim + "'")
		)
		else
		(
			python.Execute "_powerusd_default_prim = None"
		)

		python.Execute ("_powerusd_start_frame = " + (startFrame as integer) as string)
		python.Execute ("_powerusd_end_frame = " + (endFrame as integer) as string)
		python.Execute ("_powerusd_fps = " + (fps as integer) as string)

		if inlineCameras then
			python.Execute "_powerusd_inline_cameras = True"
		else
			python.Execute "_powerusd_inline_cameras = False"
	)

	rollout rPowerUSD "Power USD Exporter" width:260
	(
		bitmap bmp_logo "Logo" fileName:"" height:50 width:240 align:#center

		group "Export Mode"
		(
			checkbox chk_advSingle "Single Export" checked:false \
				tooltip:"Exports only selected Advanced units for incremental updates.\nHierarchy metadata is not rewritten."
		)

		group "Options"
		(
			checkbox chk_thumbnail "Generate Thumbnails" checked:false
			checkbox chk_hierFolders "Folders by Hierarchy" checked:false tooltip:"Mirror scene hierarchy (helper names) into subfolders."
			checkbox chk_layerFolders "Folders by Layer" checked:false tooltip:"Mirror layer hierarchy into subfolders."
		)

		group "MaterialX"
		(
			checkbox chk_force_mtlx "Force MaterialX Sidecar" checked:false tooltip:"Run the MaterialX postpass on every exported USD. Files without MaterialX content fall back to UsdPreviewSurface with no sidecar written."
			checkbox chk_inline_mtlx "Inline MaterialX Into USD" checked:false tooltip:"Final postpass: generate MaterialX, compose it into the exported USD, then remove the temporary .mtlx sidecar."
			checkbox chk_ref_textures "Reference Textures (no copy)" checked:true tooltip:"Emit relative texture paths in MaterialX without copying bitmaps to the export folder.\nUncheck when exporting to a standalone folder that should ship with its own texture set."
		)

		group "Assembler"
		(
			checkbox chk_autoAssemble "Auto Assemble Stage" checked:true tooltip:"Create .usda stage referencing all exports.\nRebuilds hierarchy from metadata."
			checkbox chk_rootPrim "Root Prim" checked:false tooltip:"Wrap everything under a root prim.\nUncheck to place assets at stage root."
			edittext edt_defaultPrim "Default Prim:" text:"World" fieldWidth:140 tooltip:"Top-level assembly prim name (e.g. World)."
			checkbox chk_inlineCameras "Inline Cameras" checked:false tooltip:"Write camera data directly into .usda stage.\nUncheck to use USD references for cameras."
		)

		button btn_export "EXPORT SELECTED" width:220 height:40 highlightColor:(color 0 200 0)
		button btn_export_sets "EXPORT SELECTION SETS" width:220 height:30
		button btn_genProxy "Generate Cube Proxies" width:220 height:24 tooltip:"Create bounding box proxies for selected _RENDER objects."

		on chk_advSingle changed state do
		(
			chk_autoAssemble.enabled = not state
			chk_rootPrim.enabled = not state
			edt_defaultPrim.enabled = (not state) and chk_rootPrim.checked
			chk_inlineCameras.enabled = not state
		)

		on chk_rootPrim changed state do
			edt_defaultPrim.enabled = state

		on chk_hierFolders changed state do
			if state do chk_layerFolders.checked = false

		on chk_layerFolders changed state do
			if state do chk_hierFolders.checked = false

		on rPowerUSD open do
		(
			local iconsDir = GetDir #userIcons
			local logoPath = iconsDir + "\\PowerUSD\\powerusd_logo.png"
			if doesFileExist logoPath do bmp_logo.fileName = logoPath
		)

		on btn_genProxy pressed do
		(
			if selection.count == 0 then (messageBox "No objects selected."; return false)

			local attrDefPath = PowerUSD_getScriptsDir() + "Clone_USD_AttributeDef.ms"
			if doesFileExist attrDefPath do fileIn attrDefPath

			local created = 0
			local renderObjs = for obj in selection where (matchPattern obj.name pattern:"*_RENDER*") collect obj

			if renderObjs.count == 0 then
			(
				messageBox "No _RENDER objects found in selection."
				return false
			)

			undo "Generate Cube Proxies" on
			(
				for obj in renderObjs do
				(
					local proxyName = substituteString obj.name "_RENDER" "_PROXY"
					if proxyName == obj.name do
						proxyName = substituteString obj.name "_render" "_PROXY"

					if getNodeByName proxyName != undefined do continue

					local bMin = obj.min
					local bMax = obj.max
					local bSize = bMax - bMin
					local bCenter = (bMin + bMax) / 2.0

					local proxyBox = Box length:bSize.y width:bSize.x height:bSize.z pos:[bCenter.x, bCenter.y, bMin.z]
					proxyBox.name = proxyName
					proxyBox.wirecolor = color 0 180 255

					if obj.parent != undefined do proxyBox.parent = obj.parent

					::addUSDProperties proxyBox

					created += 1
				)
			)

			format "Generated % cube proxy(s) with USD Properties\n" created
		)

		on btn_export_sets pressed do
		(
			if not PowerUSD_tryLoadMS "Clone_USD_HierarchyBuilder.ms" do return false
			if selectionSets.count == 0 then (messageBox "No Selection Sets found."; return false)

			if g_PowerUSD_lastDir == undefined do g_PowerUSD_lastDir = (getDir #export)
			local outDir = getSavePath caption:"Select Output Directory" initialDir:g_PowerUSD_lastDir
			if outDir == undefined do return false
			g_PowerUSD_lastDir = outDir

			PowerUSD_tryRunPy "Clone_USD_CleanStruct.py"
			PowerUSD_tryRunPy "Clone_USD_usdWrapper.py"
			PowerUSD_tryRunPy "Clone_USD_PropertiesChaser.py"

			local exportSets = #()
			for i = 1 to selectionSets.count do
			(
				local setName = getNamedSelSetName i
				local setNodes = for obj in selectionSets[i] collect obj
				if setNodes.count > 0 do
					append exportSets (::ExportNodeData exportName:setName rootNodes:setNodes moveRoot:undefined subFolder:undefined parentName:undefined)
			)
			exportSets = ::partitionCamerasToSingleExport exportSets cameraFileName:"Cameras"
			exportSets = ::bundleCameraTargetsInExportSets exportSets

			if not chk_hierFolders.checked and not chk_layerFolders.checked do
				for es in exportSets do es.subFolder = undefined

			local currentSel = selection as array
			local startF = animationRange.start.frame as integer
			local endF = animationRange.end.frame as integer
			local fps = frameRate as integer
			local exportSuccess = ::performBatchExport exportSets outDir false chk_thumbnail.checked startF endF fps useLegacyExport:true forceMaterialXSidecar:(chk_force_mtlx.checked or chk_inline_mtlx.checked) inlineMaterialXIntoUsd:chk_inline_mtlx.checked referenceTextures:chk_ref_textures.checked

			if exportSuccess do
			(
				select currentSel
				::writeCameraSequence outDir
				if chk_autoAssemble.checked do
				(
					local assemblerPath = PowerUSD_resolveToolPath "Clone_USD_StageAssembler.py"
					if assemblerPath != undefined do
					(
						setAssemblerPythonVars outDir (if chk_rootPrim.checked then edt_defaultPrim.text else "") startF endF fps inlineCameras:chk_inlineCameras.checked
						python.ExecuteFile assemblerPath
					)
				)
			)
		)

		on btn_export pressed do
		(
			if not PowerUSD_tryLoadMS "Clone_USD_HierarchyBuilder.ms" do return false
			local rawSelection = selection as array
			if rawSelection.count == 0 then (messageBox "No objects selected."; return false)

			-- Convert Max groups (if any) to plain Dummies BEFORE building export sets.
			-- Only runs when actual groups exist. Skips scenes with only helpers.
			local hasGroups = false
			for n in rawSelection while not hasGroups do
			(
				local c = n
				while c != undefined do (if isGroupHead c do (hasGroups = true; exit); c = c.parent)
			)
			if hasGroups do
			(
				-- Group conversion may need USDPropertiesCA to preserve USD Properties modifiers.
				if not PowerUSD_tryLoadMS "Clone_USD_AttributeDef.ms" do return false
				::convertGroupsToDummies rawSelection
			)

			if g_PowerUSD_lastDir == undefined do g_PowerUSD_lastDir = (getDir #export)
			local outDir = getSavePath caption:"Select Output Directory" initialDir:g_PowerUSD_lastDir
			if outDir == undefined do return false
			g_PowerUSD_lastDir = outDir

			PowerUSD_tryRunPy "Clone_USD_CleanStruct.py"
			PowerUSD_tryRunPy "Clone_USD_usdWrapper.py"
			PowerUSD_tryRunPy "Clone_USD_PropertiesChaser.py"

			local exportSets = #()
			local shouldWriteHierarchyMeta = false

			local useLayers = chk_layerFolders.checked

			-- Re-capture selection after group conversion (old group head refs are dead)
			if hasGroups do rawSelection = selection as array

			if chk_advSingle.checked then
			(
				exportSets = ::buildAdvancedSingleExportSets rawSelection outDir writeMetadata:false useLayers:useLayers
			)
			else
			(
				exportSets = ::buildAdvancedExportSets rawSelection outDir writeMetadata:false useLayers:useLayers
				shouldWriteHierarchyMeta = true
			)

			exportSets = ::partitionCamerasToSingleExport exportSets cameraFileName:"Cameras"
			exportSets = ::bundleCameraTargetsInExportSets exportSets

			if not chk_hierFolders.checked and not chk_layerFolders.checked do
				for es in exportSets do es.subFolder = undefined

			if shouldWriteHierarchyMeta and exportSets.count > 0 do ::writeHierarchyMetadata exportSets outDir

			local currentSel = selection as array
			local startF = animationRange.start.frame as integer
			local endF = animationRange.end.frame as integer
			local fps = frameRate as integer
			local exportSuccess = ::performBatchExport exportSets outDir false chk_thumbnail.checked startF endF fps useLegacyExport:true forceMaterialXSidecar:(chk_force_mtlx.checked or chk_inline_mtlx.checked) inlineMaterialXIntoUsd:chk_inline_mtlx.checked referenceTextures:chk_ref_textures.checked

			if exportSuccess do
			(
				try ( select (for n in rawSelection where isValidNode n collect n) ) catch ()
				::writeCameraSequence outDir
				if chk_autoAssemble.checked and not chk_advSingle.checked do
				(
					local assemblerPath = PowerUSD_resolveToolPath "Clone_USD_StageAssembler.py"
					if assemblerPath != undefined do
					(
						setAssemblerPythonVars outDir (if chk_rootPrim.checked then edt_defaultPrim.text else "") startF endF fps inlineCameras:chk_inlineCameras.checked
						python.ExecuteFile assemblerPath
					)
				)
				format "\n=== Export Complete ===\n"
			)
		)
	)

	createDialog rPowerUSD
)

(
	local selfPath = getSourceFileName()
	if selfPath != undefined and selfPath != "" do
		g_CloneTools_ScriptsDir = getFilenamePath selfPath
)

PowerUSD_InstallStartupLoader()
