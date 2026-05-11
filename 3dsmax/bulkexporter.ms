-- Author: Clone.

global g_CloneTools_ScriptsDir
global CloneUI

fn AuthorUSD_uniqueAppend arr value =
(
	if value == undefined or value == "" do return arr
	local v = value as string
	for e in arr where (toLower (e as string)) == (toLower v) do return arr
	append arr v
	arr
)

fn AuthorUSD_detectSourceDir selfFileName =
(
	local candidates = #()
	if ::g_CloneTools_ScriptsDir != undefined and ::g_CloneTools_ScriptsDir != "" do
		AuthorUSD_uniqueAppend candidates ::g_CloneTools_ScriptsDir

	local pA = try(getSourceFileName())catch("")
	if pA != undefined and pA != "" do AuthorUSD_uniqueAppend candidates (getFilenamePath pA)

	local pB = try(sourceFileName)catch("")
	if pB != undefined and pB != "" do AuthorUSD_uniqueAppend candidates (getFilenamePath pB)

	local pC = try(sysInfo.currentdir)catch("")
	if pC != undefined and pC != "" do AuthorUSD_uniqueAppend candidates pC

	AuthorUSD_uniqueAppend candidates ((getDir #userScripts) + "\\CloneTools\\")

	for dir in candidates do (
		local direct = dir + selfFileName
		local fromChasers = dir + "cloneTools\\" + selfFileName
		if doesFileExist direct do return dir
		if doesFileExist fromChasers do return (dir + "cloneTools\\")
	)
	undefined
)

fn AuthorUSD_findSourceFile sourceDir fileName =
(
	local p1 = sourceDir + fileName
	if doesFileExist p1 do return p1
	local p2 = sourceDir + "cloneTools\\" + fileName
	if doesFileExist p2 do return p2
	""
)

fn AuthorUSD_copyFile sourcePath destPath =
(
	if sourcePath == undefined or sourcePath == "" do return false
	if destPath == undefined or destPath == "" do return false
	if not doesFileExist sourcePath do return false

	if (toLower sourcePath) == (toLower destPath) do return true
	if doesFileExist destPath do deleteFile destPath
	copyFile sourcePath destPath
)

fn PowerUSD_getScriptsDir =
(
	-- The install layout places every Clone_USD_* helper flat under
	-- <userScripts>/CloneTools/. The repo keeps them beside this script in
	-- 3dsmax/cloneTools/. Probe candidates in order of preference and return
	-- whichever one actually contains Clone_USD_HierarchyBuilder.ms (the
	-- canonical dependency). Falls back to the install path unconditionally.
	local sentinel = "Clone_USD_HierarchyBuilder.ms"
	local candidates = #()
	if g_CloneTools_ScriptsDir != undefined and g_CloneTools_ScriptsDir != "" do
	(
		append candidates g_CloneTools_ScriptsDir
		append candidates (g_CloneTools_ScriptsDir + "cloneTools\\")
		append candidates (g_CloneTools_ScriptsDir + "cloneTools/")
	)
	append candidates ((getDir #userScripts) + "/CloneTools/")

	local chosen = undefined
	for c in candidates while chosen == undefined do
		if doesFileExist (c + sentinel) do chosen = c

	if chosen == undefined then ((getDir #userScripts) + "/CloneTools/")
	else chosen
)

fn AuthorUSD_escapePath path = (substituteString path "\\" "\\\\")

fn AuthorUSD_isWritableDir dirPath =
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

fn AuthorUSD_InstallStartupLoader =
(
	local selfFile = "bulkexporter.ms"
	local deps = #(
		"Clone_USD_HierarchyBuilder.ms",
		"Clone_USD_CleanStruct.py",
		"Clone_USD_usdWrapper.py",
		"Clone_USD_PropertiesChaser.py",
		"Clone_USD_MaterialXSidecar.py",
		"Clone_USD_ExportBridge.py",
		"Clone_USD_AttributeDef.ms",
		"CloneUI.ms"
	)
	local sourceDir = AuthorUSD_detectSourceDir selfFile
	if sourceDir == undefined or sourceDir == "" do return false
	local sourceFile = AuthorUSD_findSourceFile sourceDir selfFile
	if sourceFile == "" do return false

	local targetDir = (getDir #userScripts) + "\\CloneTools\\"
	try(makeDir targetDir)catch()
	local destPath = targetDir + selfFile
	AuthorUSD_copyFile sourceFile destPath

	for dep in deps do (
		local src = AuthorUSD_findSourceFile sourceDir dep
		if src != "" do AuthorUSD_copyFile src (targetDir + dep)
	)
	if doesFileExist (sourceDir + "icons\\powerusd_logo.png") do AuthorUSD_copyFile (sourceDir + "icons\\powerusd_logo.png") (targetDir + "powerusd_logo.png")

	local userMacrosDir = getDir #userMacros
	if userMacrosDir != undefined and userMacrosDir != "" and AuthorUSD_isWritableDir userMacrosDir do (
		-- Remove legacy BulkUSD-branded installer artifact if present.
		local legacyMcrPath = userMacrosDir + "\\BulkUSDExport_CloneTools.mcr"
		if doesFileExist legacyMcrPath do try(deleteFile legacyMcrPath)catch()

		local mcrPath = userMacrosDir + "\\AuthorUSDExport_CloneTools.mcr"
		if doesFileExist mcrPath do deleteFile mcrPath
		AuthorUSD_copyFile sourceFile mcrPath
	)

	local startupDirs = #()
	local d1 = try(getDir #userStartupScripts)catch("")
	if d1 != undefined and d1 != "" do append startupDirs d1
	append startupDirs ((getDir #userScripts) + "\\startup")
	local d2 = try(getDir #startupScripts)catch("")
	if d2 != undefined and d2 != "" do append startupDirs d2

	local macroPaths = #()
	AuthorUSD_uniqueAppend macroPaths sourceFile
	AuthorUSD_uniqueAppend macroPaths destPath
	local macroList = ""
	for i = 1 to macroPaths.count do (
		local comma = if i < macroPaths.count then "," else ""
		macroList += ("\t\t\"" + (AuthorUSD_escapePath macroPaths[i]) + "\"" + comma + "\n")
	)

	local loaderScript =
		"-- Auto-generated by AuthorUSD\n" +
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

	for startupDir in startupDirs do (
		if AuthorUSD_isWritableDir startupDir do (
			-- Remove legacy BulkUSD loader stub so it doesn't double-register.
			local legacyLoaderPath = startupDir + "\\BulkUSD_LoadMacros.ms"
			if doesFileExist legacyLoaderPath do try(deleteFile legacyLoaderPath)catch()

			local loaderPath = startupDir + "\\AuthorUSD_LoadMacros.ms"
			try (
				local f = createFile loaderPath
				format "%" loaderScript to:f
				close f
			) catch ()
		)
	)

	true
)

macroScript PowerUSDBulkExport
category:"CloneTools"
toolTip:"Author USD"
buttonText:"Author USD"
(
	persistent global g_PowerUSD_lastDir

	try(if CloneUI == undefined do fileIn ((getDir #userScripts) + "\\CloneTools\\CloneUI.ms"))catch(fileIn (PowerUSD_getScriptsDir() + "CloneUI.ms"))
	try(PowerUSDBulkExport_Form.Close())catch()
	try(PowerUSDBulkExport_Form.Dispose())catch()
	global PowerUSDBulkExport_Form = dotNetObject "System.Windows.Forms.Form"

	local frm = CloneUI.skinForm PowerUSDBulkExport_Form "Author USD" 360 560
	local shell = CloneUI.addShell frm "Author USD" version:"v1.0"
	local pad = shell[1]
	local iW = shell[2]
	local Y = shell[3]

	frm.controls.add (CloneUI.mkLabel "GROUPING" pad Y iW 18 fObj:CloneUI.fBold cObj:CloneUI.cHead); Y += 26
	local chk_layers = CloneUI.mkCheck "By Layers" (pad+4) Y 140 chk:false
	local chk_hierarchy = CloneUI.mkCheck "By Hierarchies" (pad+164) Y 160 chk:true
	frm.controls.add chk_layers
	frm.controls.add chk_hierarchy
	Y += 38

	frm.controls.add (CloneUI.mkSep pad Y iW); Y += 12
	frm.controls.add (CloneUI.mkLabel "OPTIONS" pad Y iW 18 fObj:CloneUI.fBold cObj:CloneUI.cHead); Y += 26
	local chk_origin = CloneUI.mkCheck "Move to Origin" (pad+4) Y 150 chk:false
	local chk_thumbnail = CloneUI.mkCheck "Generate Thumbnails" (pad+164) Y 170 chk:false
	frm.controls.add chk_origin
	frm.controls.add chk_thumbnail
	Y += 28
	local chk_force_mtlx = CloneUI.mkCheck "Force MaterialX Sidecar" (pad+4) Y 220 chk:false
	frm.controls.add chk_force_mtlx
	Y += 28
	local chk_inline_mtlx = CloneUI.mkCheck "Inline MaterialX Into USD" (pad+4) Y 230 chk:false
	frm.controls.add chk_inline_mtlx
	Y += 28
	local chk_ref_textures = CloneUI.mkCheck "Reference Textures (no copy)" (pad+4) Y 245 chk:true
	frm.controls.add chk_ref_textures
	Y += 42

	local btn_export = CloneUI.mkBtn "EXPORT SELECTED" pad Y iW 38
	local btn_export_sets = CloneUI.mkBtn "EXPORT SELECTION SETS" pad (Y + 46) iW 30
	frm.controls.add btn_export
	frm.controls.add btn_export_sets
	Y += 96

	local credit = CloneUI.mkLabel "clone" 0 Y 360 16 fObj:CloneUI.fSmall cObj:(CloneUI.clr.FromArgb 55 55 55)
	credit.TextAlign = CloneUI.alC.MiddleCenter
	frm.controls.add credit
	frm.Size = dotNetObject CloneUI.szC 360 (Y + 24)

	fn onLayersChanged s e = (if chk_layers.Checked do chk_hierarchy.Checked = false)
	fn onHierarchyChanged s e = (if chk_hierarchy.Checked do chk_layers.Checked = false)

	fn runPowerUSDPrep =
	(
		local scriptsDir = PowerUSD_getScriptsDir()
		if doesFileExist (scriptsDir + "Clone_USD_CleanStruct.py") do python.ExecuteFile (scriptsDir + "Clone_USD_CleanStruct.py")
		if doesFileExist (scriptsDir + "Clone_USD_usdWrapper.py") do python.ExecuteFile (scriptsDir + "Clone_USD_usdWrapper.py")
		if doesFileExist (scriptsDir + "Clone_USD_PropertiesChaser.py") do python.ExecuteFile (scriptsDir + "Clone_USD_PropertiesChaser.py")
	)

	fn onExportSets s e =
	(
		fileIn (PowerUSD_getScriptsDir() + "Clone_USD_HierarchyBuilder.ms")
		if selectionSets.count == 0 then (messageBox "No Selection Sets found."; return false)

		if g_PowerUSD_lastDir == undefined do g_PowerUSD_lastDir = (getDir #export)
		local outDir = getSavePath caption:"Select Output Directory" initialDir:g_PowerUSD_lastDir
		if outDir == undefined do return false
		g_PowerUSD_lastDir = outDir

		runPowerUSDPrep()

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

		local currentSel = selection as array
		local startF = animationRange.start.frame as integer
		local endF = animationRange.end.frame as integer
		local fps = frameRate as integer
		local exportSuccess = ::performBatchExport exportSets outDir chk_origin.Checked chk_thumbnail.Checked startF endF fps forceMaterialXSidecar:(chk_force_mtlx.Checked or chk_inline_mtlx.Checked) inlineMaterialXIntoUsd:chk_inline_mtlx.Checked referenceTextures:chk_ref_textures.Checked

		if exportSuccess do
		(
			select currentSel
			format "\n=== Author USD Export Complete ===\n"
		)
	)

	fn onExportSelected s e =
	(
		fileIn (PowerUSD_getScriptsDir() + "Clone_USD_HierarchyBuilder.ms")
		local rawSelection = selection as array
		if rawSelection.count == 0 then (messageBox "No objects selected."; return false)

		if g_PowerUSD_lastDir == undefined do g_PowerUSD_lastDir = (getDir #export)
		local outDir = getSavePath caption:"Select Output Directory" initialDir:g_PowerUSD_lastDir
		if outDir == undefined do return false
		g_PowerUSD_lastDir = outDir

		runPowerUSDPrep()

		local exportSets = #()

		-- LAYERS: all objects on layer exported together
		if chk_layers.Checked then
		(
			local layerNames = #()

			for obj in rawSelection do
			(
				local lName = obj.layer.name
				if findItem layerNames lName == 0 do append layerNames lName
			)

			for lName in layerNames do
			(
				local layer = LayerManager.getLayerFromName lName
				local layerNodes = #()
				layer.nodes &layerNodes
				append exportSets (::ExportNodeData exportName:lName rootNodes:layerNodes moveRoot:undefined subFolder:undefined parentName:undefined)
			)
		)
		-- HIERARCHIES: entire hierarchy exported together
		else if chk_hierarchy.Checked then
		(
			local processedRoots = #()

			for obj in rawSelection do
			(
				local root = ::getHierarchyRoot obj
				if findItem processedRoots root == 0 do
				(
					append processedRoots root
					local fullTree = ::getAllDescendants root
					append exportSets (::ExportNodeData exportName:root.name rootNodes:fullTree moveRoot:root subFolder:undefined parentName:undefined)
				)
			)
		)
		-- STANDARD: individual objects/groups, instances exported together
		else
		(
			local groupsProcessed = #()
			local geometryObjects = #()
			local groupObjects = #()

			for obj in rawSelection do
			(
				if isGroupMember obj then
				(
					local grpHead = obj
					while (isGroupMember grpHead) do grpHead = grpHead.parent
					if findItem groupsProcessed grpHead == 0 do
					(
						append groupsProcessed grpHead
						append groupObjects grpHead
					)
				)
				else if isGroupHead obj then
				(
					if findItem groupsProcessed obj == 0 do
					(
						append groupsProcessed obj
						append groupObjects obj
					)
				)
				else
				(
					append geometryObjects obj
				)
			)

			for grp in groupObjects do
				append exportSets (::ExportNodeData exportName:grp.name rootNodes:#(grp) moveRoot:grp subFolder:undefined parentName:undefined)

			local instanceGroups = ::groupByInstances geometryObjects

			for group in instanceGroups do
			(
				local master = ::selectMasterInstance group
				append exportSets (::ExportNodeData exportName:master.name rootNodes:group moveRoot:master subFolder:undefined parentName:undefined)
			)
		)

		exportSets = ::partitionCamerasToSingleExport exportSets cameraFileName:"Cameras"
		exportSets = ::bundleCameraTargetsInExportSets exportSets

		local currentSel = selection as array
		local startF = animationRange.start.frame as integer
		local endF = animationRange.end.frame as integer
		local fps = frameRate as integer
		local exportSuccess = ::performBatchExport exportSets outDir chk_origin.Checked chk_thumbnail.Checked startF endF fps forceMaterialXSidecar:(chk_force_mtlx.Checked or chk_inline_mtlx.Checked) inlineMaterialXIntoUsd:chk_inline_mtlx.Checked referenceTextures:chk_ref_textures.Checked

		if exportSuccess do
		(
			select rawSelection
			format "\n=== Author USD Export Complete ===\n"
		)
	)

	dotNet.addEventHandler chk_layers "CheckedChanged" onLayersChanged
	dotNet.addEventHandler chk_hierarchy "CheckedChanged" onHierarchyChanged
	dotNet.addEventHandler btn_export_sets "Click" onExportSets
	dotNet.addEventHandler btn_export "Click" onExportSelected
	frm.Show()
)

(
	local selfPath = getSourceFileName()
	if selfPath != undefined and selfPath != "" do
		g_CloneTools_ScriptsDir = getFilenamePath selfPath
)

AuthorUSD_InstallStartupLoader()
