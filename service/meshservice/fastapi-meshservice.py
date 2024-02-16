import os
import subprocess
import tempfile
import zipfile
import io

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import Response

to_clean = []
app = FastAPI()

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
        print(f"Done computing {len(mesh_files)} mesh(es)")
        s = io.BytesIO()
        zf = zipfile.ZipFile(s, "w", compression=zipfile.ZIP_DEFLATED)
        zip_filename = f"{pdb_id}.zip"
        
        for filename in mesh_files:
            zip_path = os.path.join(tempdir_out.name, filename)
            zf.write(zip_path, arcname=filename)
            
        zf.close()
        to_clean.append(tempdir_out)
        return Response(s.getvalue(), media_type="application/x-zip-compressed", headers={'Content-Disposition': f'attachment;filename={zip_filename}'})


@app.get("/getmeshes/{pdb_id}")
async def read_item(pdb_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(clean)
    pdbimages = PDBImagesMesh()
    return await pdbimages.GetMesh(pdb_id)