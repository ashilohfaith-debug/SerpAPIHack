Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = "RELAY Test Window"
$form.Size = New-Object System.Drawing.Size(640, 420)
$form.StartPosition = "CenterScreen"
$form.TopMost = $true
$form.Add_Shown({ $form.Activate() })

$box = New-Object System.Windows.Forms.RichTextBox
$box.Location = New-Object System.Drawing.Point(10, 10)
$box.Size = New-Object System.Drawing.Size(600, 220)
$box.ReadOnly = $true
$box.Text = "Welcome to the RELAY reading test.`r`n`r`nThe quick brown fox jumps over the lazy dog. This second paragraph checks that continuous reading works.`r`n`r`nThe third paragraph is the last one. Thank you for testing."
$form.Controls.Add($box)

$label = New-Object System.Windows.Forms.Label
$label.Location = New-Object System.Drawing.Point(10, 240)
$label.Size = New-Object System.Drawing.Size(400, 24)
$label.Text = "Status: waiting"
$form.Controls.Add($label)

$hello = New-Object System.Windows.Forms.Button
$hello.Location = New-Object System.Drawing.Point(10, 280)
$hello.Size = New-Object System.Drawing.Size(160, 32)
$hello.Text = "Say Hello"
$hello.Add_Click({ $label.Text = "Status: hello clicked" })
$form.Controls.Add($hello)

$danger = New-Object System.Windows.Forms.Button
$danger.Location = New-Object System.Drawing.Point(190, 280)
$danger.Size = New-Object System.Drawing.Size(180, 32)
$danger.Text = "Delete Everything"
$danger.Add_Click({ $label.Text = "Status: DELETE WAS CLICKED" })
$form.Controls.Add($danger)

[void]$form.ShowDialog()
