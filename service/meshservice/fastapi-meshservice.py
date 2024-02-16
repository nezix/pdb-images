import os
import subprocess
import tempfile

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.gzip import GZipMiddleware

to_clean = []
app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)

def clean():
    global to_clean
    for temp in to_clean:
        print(f"Cleaning {temp.name}")
        temp.cleanup()
    to_clean = []

class PDBImagesMesh():
    def run_pdb_images_pdbid(self, pdbId: str, output_folder: str, arguments: dict= {}):
        if not len(arguments):
            arguments ={"repMode": "mesh", "showHydrogens":False, "showBranchedSticks":True, "ensembleShades":False, "forceBfactor":False}
            
        args = ["xvfb-run", "--auto-servernum", "pdb-images", pdbId, output_folder, "--type", arguments["repMode"]]
        if "showHydrogens" in arguments and arguments["showHydrogens"]:
            args += ["--show-hydrogens"]
        if "showBranchedSticks" in arguments and arguments["showBranchedSticks"]:
            args += ["--show-branched-sticks"]
        if "ensembleShades" in arguments and arguments["ensembleShades"]:
            args += ["--ensemble-shades"]
        if "forceBfactor" in arguments and arguments["forceBfactor"]:
            args += ["--force-bfactor"]

        print(f"Starting with args: {args}")

        result = subprocess.run(args, capture_output=True)
        if len(result.stderr) > 0:
            return result.stderr.decode("utf-8")
        return ""

    async def GetMesh(self, pdb_id: str, arguments: dict = {}):
        global to_clean
        print("Run pdb-images for " + pdb_id)
        tempdir_out = tempfile.TemporaryDirectory(prefix="pdb_images_output_")
        ret = self.run_pdb_images_pdbid(pdb_id.lower(), tempdir_out.name, arguments)
        if ret:
            raise Exception(f"Something went wrong when executing pdb-images: {ret}")

        mesh_files = [filename for filename in os.listdir(tempdir_out.name) if filename.endswith(".usdz")]
        if len(mesh_files) == 0:
            raise Exception(f"Something went wrong when executing pdb-images, no usdz file written")
        
        to_clean.append(tempdir_out)
        return FileResponse(path=os.path.join(tempdir_out.name, mesh_files[0]), filename=mesh_files[0])


@app.get("/getmesh/{pdb_id}")
async def read_item(pdb_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(clean)
    pdbimages = PDBImagesMesh()
    return await pdbimages.GetMesh(pdb_id)