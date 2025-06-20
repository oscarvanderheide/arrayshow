import sys

from .viewer import NDArrayViewer

# --- Import PyQt5 directly ---
try:
    from PyQt5 import QtWidgets
except ImportError:
    print(
        "Error: This application requires PyQt5. Please install it (`pip install pyqt5`)."
    )
    sys.exit(1)


__version__ = "0.1.0"
__all__ = ["arrayshow"]


def arrayshow(array, remote=None, fallback_matplotlib=True):
    """Display an interactive view of a multidimensional array.

    Args:
        array: numpy array with at least 2 dimensions
        remote: bool, optional. Set to True to enable remote/SSH compatibility mode.
                If None, auto-detects based on environment variables.
        fallback_matplotlib: bool, optional. If True, fall back to matplotlib viewer
                when VisPy fails (useful for SSH connections).

    Returns:
        None
    """
    import os
    
    # Handle remote parameter
    if remote is not None:
        os.environ['ARRAYSHOW_REMOTE'] = '1' if remote else '0'
    
    # Check if we're in remote mode
    is_remote = any([
        'SSH_CLIENT' in os.environ,
        'SSH_CONNECTION' in os.environ,
        'SSH_TTY' in os.environ,
        os.environ.get('DISPLAY', '').startswith(':'),
        os.environ.get('ARRAYSHOW_REMOTE', '0') == '1',
    ])

    try:
        app = QtWidgets.QApplication(sys.argv)
        viewer = NDArrayViewer(array)
        print("\nVisPy viewer started.")
        viewer.show()
        sys.exit(app.exec())
        
    except Exception as e:
        print(f"\nVisPy viewer failed: {e}")
        
        if fallback_matplotlib and is_remote:
            print("Falling back to matplotlib-based viewer for SSH compatibility...")
            try:
                from .matplotlib_fallback import arrayshow_matplotlib
                arrayshow_matplotlib(array, "Array Viewer (SSH Mode)")
                return None
            except Exception as e2:
                print(f"Matplotlib fallback also failed: {e2}")
                raise e2
        else:
            print("Set fallback_matplotlib=True to try matplotlib viewer")
            raise e
    
    return None
