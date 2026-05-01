global CloneUI
global CloneUI_handlers
global CloneUI_drag
global CloneUI_dragPt
global CloneUI_dragForm

CloneUI_handlers = #()
CloneUI_drag = false
CloneUI_dragPt = undefined
CloneUI_dragForm = undefined

fn CloneUI_releaseImages ctrl =
(
	try
	(
		if ((ctrl.GetType()).FullName as string) == "System.Windows.Forms.PictureBox" do
		(
			local img = ctrl.Image
			if img != undefined do
			(
				try(ctrl.Image = undefined)catch()
				try(img.Dispose())catch()
			)
		)
	)
	catch()

	try
	(
		for i = 0 to (ctrl.Controls.Count - 1) do CloneUI_releaseImages (ctrl.Controls.Item[i])
	)
	catch()
)

fn CloneUI_onFormClosed s e =
(
	CloneUI_releaseImages s
	CloneUI_drag = false
	CloneUI_dragPt = undefined
	if CloneUI_dragForm == s do CloneUI_dragForm = undefined
)

fn CloneUI_onClose s e =
(
	try((s.FindForm()).Close())catch()
)

fn CloneUI_onXEnter s e =
(
	s.ForeColor = (dotNetClass "System.Drawing.Color").FromArgb 255 80 80
)

fn CloneUI_onXLeave s e =
(
	s.ForeColor = (dotNetClass "System.Drawing.Color").FromArgb 120 120 120
)

fn CloneUI_onPaint s e =
(
	local clrC = dotNetClass "System.Drawing.Color"
	local c1 = clrC.FromArgb 35 35 40
	local c2 = clrC.FromArgb 20 20 22
	local rect = dotNetObject "System.Drawing.Rectangle" 0 0 s.Width s.Height
	local brush = dotNetObject "System.Drawing.Drawing2D.LinearGradientBrush" rect c1 c2 (dotNetClass "System.Drawing.Drawing2D.LinearGradientMode").Vertical
	e.Graphics.FillRectangle brush rect
	brush.Dispose()
	local pen = dotNetObject "System.Drawing.Pen" (clrC.FromArgb 55 55 55) 1.0
	e.Graphics.DrawRectangle pen 0 0 (s.Width - 1) (s.Height - 1)
	pen.Dispose()
)

fn CloneUI_onDragDown s e =
(
	if e.Button == (dotNetClass "System.Windows.Forms.MouseButtons").Left do
	(
		CloneUI_drag = true
		CloneUI_dragForm = s.FindForm()
		local mPos = (dotNetClass "System.Windows.Forms.Control").MousePosition
		local fLoc = CloneUI_dragForm.Location
		CloneUI_dragPt = dotNetObject "System.Drawing.Point" (fLoc.X - mPos.X) (fLoc.Y - mPos.Y)
	)
)

fn CloneUI_onDragMove s e =
(
	if CloneUI_drag and CloneUI_dragPt != undefined and CloneUI_dragForm != undefined do
	(
		if e.Button != (dotNetClass "System.Windows.Forms.MouseButtons").Left then CloneUI_drag = false
		else
		(
			local mPos = (dotNetClass "System.Windows.Forms.Control").MousePosition
			CloneUI_dragForm.Location = dotNetObject "System.Drawing.Point" (mPos.X + CloneUI_dragPt.X) (mPos.Y + CloneUI_dragPt.Y)
		)
	)
)

fn CloneUI_onDragUp s e =
(
	CloneUI_drag = false
)

fn CloneUI_onKey s e =
(
	if e.KeyCode == e.KeyCode.Escape do try((s.FindForm()).Close())catch()
)

fn CloneUI_addDrag ctrl =
(
	dotNet.addEventHandler ctrl "MouseDown" CloneUI_onDragDown
	dotNet.addEventHandler ctrl "MouseMove" CloneUI_onDragMove
	dotNet.addEventHandler ctrl "MouseUp" CloneUI_onDragUp
)

struct CloneUIStruct
(
	clr = dotNetClass "System.Drawing.Color",
	fntC = dotNetClass "System.Drawing.Font",
	fntS = dotNetClass "System.Drawing.FontStyle",
	szC = dotNetClass "System.Drawing.Size",
	ptC = dotNetClass "System.Drawing.Point",
	alC = dotNetClass "System.Drawing.ContentAlignment",
	curC = dotNetClass "System.Windows.Forms.Cursors",
	flatC = dotNetClass "System.Windows.Forms.FlatStyle",

	cBg = (dotNetClass "System.Drawing.Color").FromArgb 30 30 30,
	cSep = (dotNetClass "System.Drawing.Color").FromArgb 55 55 55,
	cText = (dotNetClass "System.Drawing.Color").FromArgb 200 200 200,
	cDim = (dotNetClass "System.Drawing.Color").FromArgb 120 120 120,
	cHead = (dotNetClass "System.Drawing.Color").FromArgb 150 150 150,
	cBtnBg = (dotNetClass "System.Drawing.Color").FromArgb 50 50 50,
	cBtnBd = (dotNetClass "System.Drawing.Color").FromArgb 70 70 70,
	cBtnHov = (dotNetClass "System.Drawing.Color").FromArgb 65 65 65,

	fBold = dotNetObject "System.Drawing.Font" "Segoe UI" 8.5 (dotNetClass "System.Drawing.FontStyle").Bold,
	fNorm = dotNetObject "System.Drawing.Font" "Segoe UI" 8.5 (dotNetClass "System.Drawing.FontStyle").Regular,
	fSmall = dotNetObject "System.Drawing.Font" "Segoe UI" 7.5 (dotNetClass "System.Drawing.FontStyle").Regular,

	fn logoPath toolTitle:"" =
	(
		local candidates = #()
		local sourceDir = try(getFilenamePath (getSourceFileName()))catch("")
		local isPowerUSD = matchPattern (toLower (toolTitle as string)) pattern:"*usd*"
		if isPowerUSD then
		(
			if sourceDir != undefined and sourceDir != "" do
			(
				append candidates (sourceDir + "icons\\powerusd_logo.png")
				append candidates (sourceDir + "powerusd_logo.png")
			)
			append candidates ((getDir #userScripts) + "\\CloneTools\\powerusd_logo.png")
			append candidates ((getDir #userIcons) + "\\PowerUSD\\powerusd_logo.png")
			append candidates @"C:\Users\ogulc\Clone Library\ClonePipeline\powerusdexporter\3dsmax\icons\powerusd_logo.png"
			append candidates @"C:\Users\ogulc\Clone Library\ClonePipeline\powerusdexporter\docs\Logo.png"
		)
		else
		(
			if sourceDir != undefined and sourceDir != "" do append candidates (sourceDir + "images\\Logo.png")
			append candidates ((getDir #userScripts) + "\\CloneTools\\images\\Logo.png")
			append candidates @"C:\Users\ogulc\Clone Library\ClonePipeline\clone-maxscripts\images\Logo.png"
		)
		if not isPowerUSD do
		(
			append candidates ((getDir #userScripts) + "\\CloneTools\\powerusd_logo.png")
			append candidates @"C:\Users\ogulc\Clone Library\ClonePipeline\powerusdexporter\3dsmax\icons\powerusd_logo.png"
		)
		if isPowerUSD do
		(
			append candidates ((getDir #userScripts) + "\\CloneTools\\images\\Logo.png")
			append candidates @"C:\Users\ogulc\Clone Library\ClonePipeline\clone-maxscripts\images\Logo.png"
		)
		for p in candidates where doesFileExist p do return p
		""
	),

	fn mkLabel txt x y w h fObj:undefined cObj:undefined =
	(
		local l = dotNetObject "System.Windows.Forms.Label"
		l.Text = txt
		l.AutoSize = false
		l.Location = dotNetObject ptC x y
		l.Size = dotNetObject szC w h
		l.ForeColor = if cObj != undefined then cObj else cText
		l.BackColor = clr.Transparent
		if fObj != undefined do l.Font = fObj
		l
	),

	fn mkBtn txt x y w h =
	(
		local b = dotNetObject "System.Windows.Forms.Button"
		b.Text = txt
		b.Location = dotNetObject ptC x y
		b.Size = dotNetObject szC w h
		b.FlatStyle = flatC.Flat
		b.FlatAppearance.BorderColor = cBtnBd
		b.FlatAppearance.BorderSize = 1
		b.FlatAppearance.MouseOverBackColor = cBtnHov
		b.BackColor = cBtnBg
		b.ForeColor = cText
		b.Font = fNorm
		b.Cursor = curC.Hand
		b
	),

	fn mkSep x y w =
	(
		local p = dotNetObject "System.Windows.Forms.Panel"
		p.Location = dotNetObject ptC x y
		p.Size = dotNetObject szC w 1
		p.BackColor = cSep
		p
	),

	fn mkCheck txt x y w chk:true =
	(
		local c = dotNetObject "System.Windows.Forms.CheckBox"
		c.Text = txt
		c.Location = dotNetObject ptC x y
		c.Size = dotNetObject szC w 22
		c.ForeColor = cText
		c.BackColor = cBg
		c.Checked = chk
		c.Font = fNorm
		c
	),

	fn mkText x y w h text:"" readOnly:false =
	(
		local t = dotNetObject "System.Windows.Forms.TextBox"
		t.Location = dotNetObject ptC x y
		t.Size = dotNetObject szC w h
		t.Text = text
		t.ReadOnly = readOnly
		t.BackColor = clr.FromArgb 38 38 38
		t.ForeColor = cText
		t.BorderStyle = (dotNetClass "System.Windows.Forms.BorderStyle").FixedSingle
		t.Font = fNorm
		t
	),

	fn mkNumeric x y w minVal maxVal value =
	(
		local n = dotNetObject "System.Windows.Forms.NumericUpDown"
		n.Location = dotNetObject ptC x y
		n.Size = dotNetObject szC w 22
		n.Minimum = minVal
		n.Maximum = maxVal
		n.Value = value
		n.BackColor = clr.FromArgb 38 38 38
		n.ForeColor = cText
		n.Font = fNorm
		n
	),

	fn skinForm frm title w initialH =
	(
		frm.Text = title
		frm.FormBorderStyle = (dotNetClass "System.Windows.Forms.FormBorderStyle").None
		frm.StartPosition = (dotNetClass "System.Windows.Forms.FormStartPosition").CenterScreen
		frm.BackColor = cBg
		frm.ForeColor = cText
		frm.ShowInTaskbar = true
		frm.TopMost = true
		frm.Opacity = 0.96
		frm.Font = fNorm
		frm.KeyPreview = true
		frm.Size = dotNetObject szC w initialH
		frm
	),

	fn addShell frm toolTitle version:"v1.0" contentY:205 =
	(
		local w = frm.Width
		local logoP = dotNetObject "System.Windows.Forms.Panel"
		logoP.Location = dotNetObject ptC 0 0
		logoP.Size = dotNetObject szC w 200
		logoP.BackColor = cBg

		local pic = dotNetObject "System.Windows.Forms.PictureBox"
		pic.Location = dotNetObject ptC 0 5
		pic.Size = dotNetObject szC w 175
		pic.SizeMode = (dotNetClass "System.Windows.Forms.PictureBoxSizeMode").Zoom
		pic.BackColor = cBg
		try
		(
			local lp = logoPath toolTitle:toolTitle
			if lp != "" and doesFileExist lp do
			(
				local fs = dotNetObject "System.IO.FileStream" lp (dotNetClass "System.IO.FileMode").Open (dotNetClass "System.IO.FileAccess").Read (dotNetClass "System.IO.FileShare").ReadWrite
				local img = (dotNetClass "System.Drawing.Image").FromStream fs
				pic.Image = dotNetObject "System.Drawing.Bitmap" img
				img.Dispose()
				fs.Close()
			)
		)
		catch ()
		logoP.controls.add pic

		local vLbl = mkLabel version 0 180 w 18 fObj:fSmall cObj:cDim
		vLbl.TextAlign = alC.MiddleCenter
		logoP.controls.add vLbl
		frm.controls.add logoP

		local xBtn = mkLabel "X" (w - 30) 5 24 24 cObj:cDim
		xBtn.Font = dotNetObject fntC "Segoe UI" 10 fntS.Bold
		xBtn.TextAlign = alC.MiddleCenter
		xBtn.Cursor = curC.Hand
		frm.controls.add xBtn
		xBtn.BringToFront()

		local pad = 16
		local iW = w - pad * 2
		frm.controls.add (mkSep pad contentY iW)
		local titleLbl = mkLabel (toUpper toolTitle) pad (contentY + 12) iW 18 fObj:fBold cObj:cHead
		frm.controls.add titleLbl

		dotNet.addEventHandler frm "Paint" CloneUI_onPaint
		dotNet.addEventHandler xBtn "Click" CloneUI_onClose
		dotNet.addEventHandler xBtn "MouseEnter" CloneUI_onXEnter
		dotNet.addEventHandler xBtn "MouseLeave" CloneUI_onXLeave
		dotNet.addEventHandler frm "KeyUp" CloneUI_onKey
		dotNet.addEventHandler frm "FormClosed" CloneUI_onFormClosed
		CloneUI_addDrag frm
		CloneUI_addDrag logoP
		CloneUI_addDrag pic
		CloneUI_addDrag vLbl
		CloneUI_addDrag titleLbl
		CloneUI_addDrag xBtn
		#(pad, iW, contentY + 42)
	)
)

CloneUI = CloneUIStruct()
