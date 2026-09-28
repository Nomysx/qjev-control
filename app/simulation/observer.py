from app.config import PlantParameters
from app.simulation.plant import Motor


class NominalPredictor(Motor):
    """Parallel nominal model driven by commanded voltage, with no fault information."""

    def __init__(self, parameters: PlantParameters):
        super().__init__(parameters)
