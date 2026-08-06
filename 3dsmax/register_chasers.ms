-- Author: Clone.

global g_CloneTools_ScriptsDir

fn PowerUSDChasers_uniqueAppend arr value =
(
	if value == undefined or value == "" do return arr
	local v = value as string
	for e in arr where (toLower (e as string)) == (toLower v) do return arr
	append arr v
	arr
)

fn PowerUSDChasers_detectSourceDir selfFileName =
(
	local candidates = #()
	if ::g_CloneTools_ScriptsDir != undefined and ::g_CloneTools_ScriptsDir != "" do
		PowerUSDChasers_uniqueAppend candidates ::g_CloneTools_ScriptsDir

	local pA = try(getSourceFileName())catch("")
	if pA != undefined and pA != "" do PowerUSDChasers_uniqueAppend candidates (getFilenamePath pA)

	local pB = try(sourceFileName)catch("")
	if pB != undefined and pB != "" do PowerUSDChasers_uniqueAppend candidates (getFilenamePath pB)

	local pC = try(sysInfo.currentdir)catch("")
	if pC != undefined and pC != "" do PowerUSDChasers_uniqueAppend candidates pC

	PowerUSDChasers_uniqueAppend candidates ((getDir #userScripts) + "\\CloneTools\\")

	for dir in candidates do (
		local direct = dir + selfFileName
		local fromTools = dir + "cloneTools\\" + selfFileName
		if doesFileExist direct do return dir
		if doesFileExist fromTools do return (dir + "cloneTools\\")
	)
	undefined
)

fn PowerUSDChasers_findSourceFile sourceDir fileName =
(
	local p1 = sourceDir + fileName
	if doesFileExist p1 do return p1
	local p2 = sourceDir + "cloneTools\\" + fileName
	if doesFileExist p2 do return p2
	""
)

fn PowerUSDChasers_copyFile sourcePath destPath =
(
	if sourcePath == undefined or sourcePath == "" do return false
	if destPath == undefined or destPath == "" do return false
	if not doesFileExist sourcePath do return false

	if (toLower sourcePath) == (toLower destPath) do return true
	if doesFileExist destPath do deleteFile destPath
	copyFile sourcePath destPath
)

fn PowerUSDChasers_isWritableDir dirPath =
(
	if dirPath == undefined or dirPath == "" do return false
	try (
		makeDir dirPath
		local probe = dirPath + "\\_powerusd_chasers_write_test.tmp"
		local f = createFile probe
		close f
		deleteFile probe
		true
	) catch (false)
)

fn PowerUSDChasers_installSelf =
(
	local selfFile = "register_chasers.ms"
	local sourceDir = PowerUSDChasers_detectSourceDir selfFile
	if sourceDir == undefined or sourceDir == "" do return false

	local sourceFile = PowerUSDChasers_findSourceFile sourceDir selfFile
	if sourceFile == "" do return false

	local targetDir = (getDir #userScripts) + "\\CloneTools\\"
	try(makeDir targetDir)catch()
	PowerUSDChasers_copyFile sourceFile (targetDir + selfFile)

	local userMacrosDir = getDir #userMacros
	if userMacrosDir != undefined and userMacrosDir != "" and PowerUSDChasers_isWritableDir userMacrosDir do
	(
		local mirrorPath = userMacrosDir + "\\PowerUSDRegisterChasers_CloneTools.mcr"
		if doesFileExist mirrorPath do deleteFile mirrorPath
		PowerUSDChasers_copyFile sourceFile mirrorPath
	)

	true
)

fn PowerUSD_getScriptsDir =
(
	local sentinel = "Clone_USD_PropertiesChaser.py"
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

global PowerUSD_RegisterChasers
fn PowerUSD_RegisterChasers quiet:false =
(
	local chaserFiles = #(
		"Clone_USD_CleanStruct.py",
		"Clone_USD_usdWrapper.py",
		"Clone_USD_PropertiesChaser.py",
		"Clone_USD_MaterialXSidecar.py"
	)

	local loaded = #()
	local missing = #()
	for f in chaserFiles do
	(
		local p = PowerUSD_resolveToolPath f
		if p == undefined then
		(
			append missing f
		)
		else
		(
			try
			(
				python.ExecuteFile p
				append loaded f
			)
			catch
			(
				append missing (f + " - " + (getCurrentException() as string))
			)
		)
	)

	format "[PowerUSD] Registered % chaser script(s): %\n" loaded.count loaded
	if missing.count > 0 do format "[PowerUSD] Missing/failed chaser script(s): %\n" missing

	if not quiet do
	(
		local message = "Registered " + (loaded.count as string) + " PowerUSD chaser script(s)."
		if missing.count > 0 do message += ("\n\nMissing/failed:\n" + (missing as string))
		messageBox message title:"PowerUSD Chasers"
	)

	missing.count == 0
)

macroScript PowerUSDRegisterChasers
category:"CloneTools"
toolTip:"Register PowerUSD USD Export Chasers"
buttonText:"Register USD Chasers"
(
	on execute do PowerUSD_RegisterChasers()
)

(
	local selfPath = getSourceFileName()
	if selfPath != undefined and selfPath != "" do
		g_CloneTools_ScriptsDir = getFilenamePath selfPath
)

PowerUSDChasers_installSelf()
