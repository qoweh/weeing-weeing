param([switch]$FromClipboard)
$ErrorActionPreference='Stop'
$tokenText=$null
$secure=$null
$buffer=[IntPtr]::Zero
$tokenBytes=$null
$hasher=$null
try {
    if ($FromClipboard) {
        # User-run only. Never print the clipboard contents or write the token to disk.
        $tokenText=Get-Clipboard -Raw
    } else {
        $secure=Read-Host 'Sensor producer token (hidden, 32+ characters)' -AsSecureString
        $buffer=[System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $tokenText=[System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($buffer)
    }
    if ([string]::IsNullOrEmpty($tokenText) -or $tokenText.Length -lt 32 -or $tokenText -match '\s') {
        throw 'Token must contain at least 32 characters and no whitespace. Clipboard contents were not displayed.'
    }
    $hasher=[System.Security.Cryptography.SHA256]::Create()
    $tokenBytes=[System.Text.Encoding]::UTF8.GetBytes($tokenText)
    $digest=[System.BitConverter]::ToString($hasher.ComputeHash($tokenBytes)).Replace('-','').ToLowerInvariant()
    Write-Output "TELEMETRY_PRODUCER_TOKEN_SHA256=$digest"
} finally {
    $tokenText=$null
    if ($tokenBytes) { [Array]::Clear($tokenBytes,0,$tokenBytes.Length) }
    if ($hasher) { $hasher.Dispose() }
    if ($buffer -ne [IntPtr]::Zero) { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($buffer) }
    if ($secure) { $secure.Dispose() }
}
