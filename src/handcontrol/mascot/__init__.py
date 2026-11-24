"""Cat mascot: copies the head, face, arms and paws of the user in the bottom-right corner.

The camera image never reaches the screen: perception turns it into a few numbers (MascotPose), the rig turns those
into bones and the renderer draws the cat. Nothing here can send OS input; any failure only hides the cat.
"""
