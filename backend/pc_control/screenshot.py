import os
import base64
import time
import subprocess
from typing import Dict, Any

def capture_desktop_screenshot(output_dir: str = None) -> Dict[str, Any]:
    """
    Capture the primary Windows display to a PNG file and return its path and base64 string.
    """
    if not output_dir:
        output_dir = os.path.join(os.path.expanduser("~"), ".kela_captures")
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = int(time.time())
    file_name = f"screenshot_{timestamp}.png"
    target_path = os.path.abspath(os.path.join(output_dir, file_name))
    
    # Write a dedicated ps1 script to avoid any command line escaping issues
    ps1_path = os.path.abspath(os.path.join(output_dir, f"_capture_{timestamp}.ps1"))
    ps_code = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bmp)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save('{target_path.replace("\\", "/")}', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bmp.Dispose()
"""
    try:
        with open(ps1_path, "w", encoding="utf-8") as f:
            f.write(ps_code)
            
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if os.path.exists(ps1_path):
            try:
                os.remove(ps1_path)
            except Exception:
                pass
                
        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            with open(target_path, "rb") as img_f:
                b64_data = base64.b64encode(img_f.read()).decode("utf-8")
            return {
                "status": "success",
                "file_path": target_path,
                "file_name": file_name,
                "size_bytes": os.path.getsize(target_path),
                "base64": f"data:image/png;base64,{b64_data}"
            }
        else:
            return {"status": "error", "message": f"Screenshot file was not created: {res.stderr}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
