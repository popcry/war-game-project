import math
from typing import Tuple, Union, List
from model.unit import Unit


# Constants

def calculate_distance(unit1: Unit, unit2: Unit) -> float:
    """Calculate the distance between two units in pixels.
    
    Args:
        unit1: First unit
        unit2: Second unit
        
    Returns:
        float: Distance in pixels
    """
    return math.sqrt(
        (unit1.position[0] - unit2.position[0]) ** 2 +
        (unit1.position[1] - unit2.position[1]) ** 2
    )

def calculate_point_distance(point1: Tuple[float, float], point2: Tuple[float, float]) -> float:
    """Calculate the distance between two points in pixels.
    
    Args:
        point1: First point coordinates (x, y)
        point2: Second point coordinates (x, y)
        
    Returns:
        float: Distance in pixels
    """
    return math.sqrt(
        (point1[0] - point2[0]) ** 2 +
        (point1[1] - point2[1]) ** 2
    )
