"""
core/heatmap.py
---------------
Generates visual similarity heatmaps using matplotlib to visually 
demonstrate to judges/managers exactly which segments were copied.
"""

import base64
import io
import matplotlib
import matplotlib.pyplot as plt

# Use Agg backend to prevent GUI windows popping up from background workers
matplotlib.use('Agg')

def generate_similarity_heatmap(
    suspect_timestamps: list[float], 
    similarities: list[float],
    matched_flags: list[bool],
    title: str = "Video Similarity Heatmap"
) -> str:
    """
    Generate a heatmap plot and return it as a Base64-encoded string.
    
    Args:
        suspect_timestamps: List of frame timestamps (seconds).
        similarities: List of Cosine similarities (0.0 to 1.0).
        matched_flags: Boolean list matching thresholds for visual coloring.
        title: Title of the generated plot.
        
    Returns:
        Base64 string representing the PNG image.
    """
    if not suspect_timestamps:
        return ""

    # Sort data by timestamp sequentially
    sorted_pairs = sorted(zip(suspect_timestamps, similarities, matched_flags), key=lambda x: x[0])
    ts = [p[0] for p in sorted_pairs]
    sims = [p[1] for p in sorted_pairs]
    colors = ['#ff4d4d' if m else '#5c8a8a' for m in [p[2] for p in sorted_pairs]]

    fig, ax = plt.subplots(figsize=(10, 3), dpi=100)
    
    # Plot bars
    ax.bar(ts, sims, width=(max(ts)/len(ts) if ts else 1), color=colors, alpha=0.8, edgecolor='black')
    
    # Styling
    ax.set_ylim(0, 1.1)
    ax.set_title(title, fontsize=12, pad=15)
    ax.set_xlabel("Suspect Video Timeline (Seconds)", fontsize=10)
    ax.set_ylabel("Cosine Similarity", fontsize=10)
    
    # Reference Line for match threshold
    ax.axhline(y=0.85, color='r', linestyle='--', linewidth=1.5, label='Match Threshold')
    ax.legend(loc="upper right")
    
    # Dark Mode formatting for the Dashboard integration
    fig.patch.set_facecolor('#1e1e1e')
    ax.set_facecolor('#1e1e1e')
    ax.xaxis.label.set_color('white')
    ax.yaxis.label.set_color('white')
    ax.title.set_color('white')
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')
    for spine in ax.spines.values():
         spine.set_edgecolor('gray')
    
    plt.tight_layout()

    # Save to memory buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor='#1e1e1e', edgecolor='none')
    plt.close(fig)
    
    # Encode to base64
    buf.seek(0)
    b64_string = base64.b64encode(buf.read()).decode('utf-8')
    
    return b64_string
