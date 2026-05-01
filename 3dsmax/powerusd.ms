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
		"Clone_USD_AttributeDef.ms",
		"CloneUI.ms"
	)
	CloneTools_installFiles selfFile extraFiles:deps
	local sourceDir = CloneTools_detectSourceDir selfFile
	if sourceDir != undefined and sourceDir != "" do
	(
		local logoSrc = sourceDir + "icons\\powerusd_logo.png"
		if doesFileExist logoSrc do CloneTools_copyFile logoSrc ((getDir #userScripts) + "\\CloneTools\\powerusd_logo.png")
	)
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

	try(if CloneUI == undefined do fileIn ((getDir #userScripts) + "\\CloneTools\\CloneUI.ms"))catch(fileIn (PowerUSD_getScriptsDir() + "CloneUI.ms"))
	try(PowerUSDExport_Form.Close())catch()
	try(PowerUSDExport_Form.Dispose())catch()
	global PowerUSDExport_Form = dotNetObject "System.Windows.Forms.Form"

	local frm = CloneUI.skinForm PowerUSDExport_Form "Power USD Exporter" 380 820
	local shell = CloneUI.addShell frm "Power USD Exporter" version:"v1.0"
	local pad = shell[1]
	local iW = shell[2]
	local Y = shell[3]

	frm.controls.add (CloneUI.mkLabel "EXPORT MODE" pad Y iW 18 fObj:CloneUI.fBold cObj:CloneUI.cHead); Y += 26
	local chk_advSingle = CloneUI.mkCheck "Single Export" (pad+4) Y 180 chk:false
	frm.controls.add chk_advSingle
	Y += 38

	frm.controls.add (CloneUI.mkSep pad Y iW); Y += 12
	frm.controls.add (CloneUI.mkLabel "OPTIONS" pad Y iW 18 fObj:CloneUI.fBold cObj:CloneUI.cHead); Y += 26
	local chk_thumbnail = CloneUI.mkCheck "Generate Thumbnails" (pad+4) Y 170 chk:false
	frm.controls.add chk_thumbnail
	Y += 28
	local chk_hierFolders = CloneUI.mkCheck "Folders by Hierarchy" (pad+4) Y 180 chk:false
	local chk_layerFolders = CloneUI.mkCheck "Folders by Layer" (pad+194) Y 150 chk:false
	frm.controls.add chk_hierFolders
	frm.controls.add chk_layerFolders
	Y += 38

	frm.controls.add (CloneUI.mkSep pad Y iW); Y += 12
	frm.controls.add (CloneUI.mkLabel "MATERIALX" pad Y iW 18 fObj:CloneUI.fBold cObj:CloneUI.cHead); Y += 26
	local chk_force_mtlx = CloneUI.mkCheck "Force MaterialX Sidecar" (pad+4) Y 230 chk:false
	frm.controls.add chk_force_mtlx
	Y += 28
	local chk_inline_mtlx = CloneUI.mkCheck "Inline MaterialX Into USD" (pad+4) Y 240 chk:false
	frm.controls.add chk_inline_mtlx
	Y += 28
	local chk_ref_textures = CloneUI.mkCheck "Reference Textures (no copy)" (pad+4) Y 250 chk:true
	frm.controls.add chk_ref_textures
	Y += 42

	frm.controls.add (CloneUI.mkSep pad Y iW); Y += 12
	frm.controls.add (CloneUI.mkLabel "ASSEMBLER" pad Y iW 18 fObj:CloneUI.fBold cObj:CloneUI.cHead); Y += 26
	local chk_autoAssemble = CloneUI.mkCheck "Auto Assemble Stage" (pad+4) Y 180 chk:true
	local chk_rootPrim = CloneUI.mkCheck "Root Prim" (pad+204) Y 130 chk:false
	frm.controls.add chk_autoAssemble
	frm.controls.add chk_rootPrim
	Y += 30
	frm.controls.add (CloneUI.mkLabel "Default Prim" (pad+4) Y 90 18 fObj:CloneUI.fSmall cObj:CloneUI.cDim)
	local edt_defaultPrim = CloneUI.mkText (pad+102) (Y-2) 150 22 text:"World"
	edt_defaultPrim.Enabled = false
	frm.controls.add edt_defaultPrim
	Y += 30
	local chk_inlineCameras = CloneUI.mkCheck "Inline Cameras" (pad+4) Y 170 chk:false
	frm.controls.add chk_inlineCameras
	Y += 42

	local btn_export = CloneUI.mkBtn "EXPORT SELECTED" pad Y iW 38
	local btn_export_sets = CloneUI.mkBtn "EXPORT SELECTION SETS" pad (Y + 46) iW 30
	local btn_genProxy = CloneUI.mkBtn "GENERATE CUBE PROXIES" pad (Y + 84) iW 28
	frm.controls.add btn_export
	frm.controls.add btn_export_sets
	frm.controls.add btn_genProxy
	Y += 124

	local credit = CloneUI.mkLabel "clone" 0 Y 380 16 fObj:CloneUI.fSmall cObj:(CloneUI.clr.FromArgb 55 55 55)
	credit.TextAlign = CloneUI.alC.MiddleCenter
	frm.controls.add credit
	frm.Size = dotNetObject CloneUI.szC 380 (Y + 24)

	fn onAdvancedSingleChanged s e =
	(
		local state = chk_advSingle.Checked
		chk_autoAssemble.Enabled = not state
		chk_rootPrim.Enabled = not state
		edt_defaultPrim.Enabled = (not state) and chk_rootPrim.Checked
		chk_inlineCameras.Enabled = not state
	)

	fn onRootPrimChanged s e = (edt_defaultPrim.Enabled = chk_rootPrim.Checked and chk_rootPrim.Enabled)
	fn onHierarchyFoldersChanged s e = (if chk_hierFolders.Checked do chk_layerFolders.Checked = false)
	fn onLayerFoldersChanged s e = (if chk_layerFolders.Checked do chk_hierFolders.Checked = false)

	fn onGenerateProxy s e =
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

	fn onExportSets s e =
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

		if not chk_hierFolders.Checked and not chk_layerFolders.Checked do
			for es in exportSets do es.subFolder = undefined

		local currentSel = selection as array
		local startF = animationRange.start.frame as integer
		local endF = animationRange.end.frame as integer
		local fps = frameRate as integer
		local exportSuccess = ::performBatchExport exportSets outDir false chk_thumbnail.Checked startF endF fps useLegacyExport:true forceMaterialXSidecar:(chk_force_mtlx.Checked or chk_inline_mtlx.Checked) inlineMaterialXIntoUsd:chk_inline_mtlx.Checked referenceTextures:chk_ref_textures.Checked

		if exportSuccess do
		(
			select currentSel
			::writeCameraSequence outDir
			if chk_autoAssemble.Checked do
			(
				local assemblerPath = PowerUSD_resolveToolPath "Clone_USD_StageAssembler.py"
				if assemblerPath != undefined do
				(
					setAssemblerPythonVars outDir (if chk_rootPrim.Checked then edt_defaultPrim.Text else "") startF endF fps inlineCameras:chk_inlineCameras.Checked
					python.ExecuteFile assemblerPath
				)
			)
		)
	)

	fn onExportSelected s e =
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

		local useLayers = chk_layerFolders.Checked

		-- Re-capture selection after group conversion (old group head refs are dead)
		if hasGroups do rawSelection = selection as array

		if chk_advSingle.Checked then
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

		if not chk_hierFolders.Checked and not chk_layerFolders.Checked do
			for es in exportSets do es.subFolder = undefined

		if shouldWriteHierarchyMeta and exportSets.count > 0 do ::writeHierarchyMetadata exportSets outDir

		local currentSel = selection as array
		local startF = animationRange.start.frame as integer
		local endF = animationRange.end.frame as integer
		local fps = frameRate as integer
		local exportSuccess = ::performBatchExport exportSets outDir false chk_thumbnail.Checked startF endF fps useLegacyExport:true forceMaterialXSidecar:(chk_force_mtlx.Checked or chk_inline_mtlx.Checked) inlineMaterialXIntoUsd:chk_inline_mtlx.Checked referenceTextures:chk_ref_textures.Checked

		if exportSuccess do
		(
			try ( select (for n in rawSelection where isValidNode n collect n) ) catch ()
			::writeCameraSequence outDir
			if chk_autoAssemble.Checked and not chk_advSingle.Checked do
			(
				local assemblerPath = PowerUSD_resolveToolPath "Clone_USD_StageAssembler.py"
				if assemblerPath != undefined do
				(
					setAssemblerPythonVars outDir (if chk_rootPrim.Checked then edt_defaultPrim.Text else "") startF endF fps inlineCameras:chk_inlineCameras.Checked
					python.ExecuteFile assemblerPath
				)
			)
			format "\n=== Export Complete ===\n"
		)
	)

	dotNet.addEventHandler chk_advSingle "CheckedChanged" onAdvancedSingleChanged
	dotNet.addEventHandler chk_rootPrim "CheckedChanged" onRootPrimChanged
	dotNet.addEventHandler chk_hierFolders "CheckedChanged" onHierarchyFoldersChanged
	dotNet.addEventHandler chk_layerFolders "CheckedChanged" onLayerFoldersChanged
	dotNet.addEventHandler btn_genProxy "Click" onGenerateProxy
	dotNet.addEventHandler btn_export_sets "Click" onExportSets
	dotNet.addEventHandler btn_export "Click" onExportSelected
	append CloneUI_handlers #(onAdvancedSingleChanged, onRootPrimChanged, onHierarchyFoldersChanged, onLayerFoldersChanged, onGenerateProxy, onExportSets, onExportSelected)
	frm.Show()
)

(
	local selfPath = getSourceFileName()
	if selfPath != undefined and selfPath != "" do
		g_CloneTools_ScriptsDir = getFilenamePath selfPath
)

PowerUSD_InstallStartupLoader()
