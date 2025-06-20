"""
Matplotlib-based fallback viewer for remote SSH connections.
"""

import numpy as np

def arrayshow_matplotlib(data, title="Array Viewer (SSH Mode)"):
    """Simple matplotlib-based array viewer for SSH compatibility."""
    try:
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Slider, Button
    except ImportError:
        raise ImportError("matplotlib is required for the SSH fallback viewer. Install with: pip install matplotlib")
    
    data = np.asarray(data)
    if data.ndim < 2:
        raise ValueError("Data must have at least 2 dimensions")
    
    # Handle complex data
    if np.iscomplexobj(data):
        is_complex = True
        display_data = np.abs(data)
        complex_mode = 'magnitude'
    else:
        is_complex = False
        display_data = data
        complex_mode = None
    
    # Simple viewer: show first 2D slice
    if data.ndim == 2:
        # Simple 2D case
        plt.figure(figsize=(10, 8))
        plt.imshow(display_data, aspect='auto', origin='lower')
        plt.colorbar()
        plt.title(f"{title}\nShape: {data.shape}")
        
        if is_complex:
            plt.suptitle(f"Complex data - showing {complex_mode}")
        
        plt.show()
        
    else:
        # Multi-dimensional case - show slices
        current_slice = [0] * data.ndim
        view_dims = [0, 1]  # Show first two dimensions
        
        fig, (ax_img, ax_cb) = plt.subplots(1, 2, figsize=(12, 6), 
                                           gridspec_kw={'width_ratios': [4, 1]})
        
        def get_slice():
            slicer = tuple(
                slice(None) if i in view_dims else current_slice[i] 
                for i in range(data.ndim)
            )
            slice_data = display_data[slicer]
            return slice_data
        
        def update_display():
            slice_data = get_slice()
            ax_img.clear()
            ax_cb.clear()
            
            im = ax_img.imshow(slice_data, aspect='auto', origin='lower')
            plt.colorbar(im, cax=ax_cb)
            
            slice_info = ', '.join([
                f'dim{i}={current_slice[i]}' 
                for i in range(data.ndim) 
                if i not in view_dims
            ])
            
            ax_img.set_title(f"{title}\nShape: {data.shape} | {slice_info}")
            if is_complex:
                fig.suptitle(f"Complex data - {complex_mode}")
            
            plt.draw()
        
        # Create simple navigation
        print(f"\n{title}")
        print(f"Data shape: {data.shape}")
        if is_complex:
            print(f"Complex data - showing {complex_mode}")
        print("Navigation:")
        for i in range(data.ndim):
            if i not in view_dims:
                print(f"  Dimension {i}: 0 to {data.shape[i]-1}")
        print("Close the plot window to continue...")
        
        update_display()
        plt.tight_layout()
        plt.show()
    
    return None
