# Blender USD guide

Building an openUSD exporter pipeline tool for dirty game exports and cinematic assets. Speed and efficent gotta be. 
But most importantly. WE ABSOLUTELY NEED INSTANCES AND MATERIALS TO NEVER BREAK!


  1. Auto-deploy powerusd → Blender 5.1 user extensions dir (and verify Blender picks it up)
  2. Inspect the actual scene structure (right now Blender shows empty — need to confirm scene is loaded)
  3. Test export to scratch dir
  4. Diagnose junk via USD inspection, iterate plugin → re-deploy → re-export
  5. Document the pattern at the end.