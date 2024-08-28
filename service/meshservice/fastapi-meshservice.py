import os
import subprocess
import tempfile
import shutil
from rdkit import Chem

from fastapi import FastAPI, BackgroundTasks, UploadFile, File
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

def pdb2cif(pdb_file: str):
    path_without_ext = os.path.splitext(os.path.basename(pdb_file))[0]
    cif_name = path_without_ext + ".cif"
    cif_path = tempfile.NamedTemporaryFile(suffix=cif_name, delete=False).name
    subprocess.run(["pdb2cif", pdb_file, cif_path])
    return cif_path

class PDBImagesMesh():
    def run_pdb_images_pdbid(self, pdbId: str, output_folder: str, arguments: dict = {}):
        if not len(arguments):
            arguments = {"repMode": "mesh", "showHydrogens": False,
                         "showBranchedSticks": True, "ensembleShades": False, "forceBfactor": False}

        args = ["xvfb-run", "--auto-servernum", "pdb-images",
                pdbId, output_folder, "--type", arguments["repMode"]]
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

    def run_pdb_images_file(self, cif_path: str, output_folder: str, arguments: dict = {}):
        if not len(arguments):
            arguments = {"repMode": "mesh", "showHydrogens": False,
                         "showBranchedSticks": True, "ensembleShades": False, "forceBfactor": False}

        args = ["xvfb-run", "--auto-servernum", "pdb-images", "--input",
                cif_path, "XXXX", output_folder, "--type", arguments["repMode"]]
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
        ret = self.run_pdb_images_pdbid(
            pdb_id.lower(), tempdir_out.name, arguments)
        if ret:
            raise Exception(
                f"Something went wrong when executing pdb-images: {ret}")

        mesh_files = [filename for filename in os.listdir(
            tempdir_out.name) if filename.endswith(".usdz")]
        if len(mesh_files) == 0:
            raise Exception(
                f"Something went wrong when executing pdb-images, no usdz file written")

        to_clean.append(tempdir_out)
        return FileResponse(path=os.path.join(tempdir_out.name, mesh_files[0]), filename=mesh_files[0])

    async def GetMeshLocal(self, file_path: str, arguments: dict = {}):
        global to_clean
        tempdir_out = tempfile.TemporaryDirectory(prefix="pdb_images_output_")
        print("Run pdb-images for " + file_path)
        to_clean.append(tempdir_out)
        shutil.move(file_path, tempdir_out.name)
        cif_path = os.path.join(tempdir_out.name, os.path.split(file_path)[1])

        ret = self.run_pdb_images_file(cif_path, tempdir_out.name, arguments)
        if ret:
            raise Exception(
                f"Something went wrong when executing pdb-images: {ret}")

        mesh_files = [filename for filename in os.listdir(
            tempdir_out.name) if filename.endswith(".usdz")]
        if len(mesh_files) == 0:
            raise Exception(
                f"Something went wrong when executing pdb-images, no usdz file written")

        to_clean.append(tempdir_out)
        return FileResponse(path=os.path.join(tempdir_out.name, mesh_files[0]), filename=mesh_files[0])

def sdfToPdb(sdf_path: str):
    path_without_ext = os.path.splitext(os.path.basename(sdf_path))[0]
    pdb_name = path_without_ext + ".pdb"
    pdb_path = tempfile.NamedTemporaryFile(suffix=pdb_name, delete=False).name
    for mol in Chem.SDMolSupplier(sdf_path):
        if mol is None:
            continue
        with Chem.PDBWriter(pdb_path) as pdb_writer:
            pdb_writer.write(mol)
        return pdb_path
    return ""

@app.get("/getmesh/{pdb_id}")
async def getmesh_pdbid(pdb_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(clean)
    pdbimages = PDBImagesMesh()
    return await pdbimages.GetMesh(pdb_id)


@app.post("/getmesh-file/")
async def getmesh_file(file: UploadFile = File(...),
                       background_tasks: BackgroundTasks = BackgroundTasks()):
    supported_ext = [".pdb", ".sdf", ".cif", ".bcif", ".cif.gz", ".bcif.gz"]
    if not any(file.filename.endswith(s) for s in supported_ext):
        raise Exception(f"Only {supported_ext} file extensions are accepted")
    
    if file.filename.endswith(".pdb"):
        pdb_path = tempfile.NamedTemporaryFile(suffix=file.filename, delete=False).name
        with open(pdb_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        file_path = pdb2cif(pdb_path)
        os.remove(pdb_path)
    elif any(file.filename.endswith(ext) for ext in [".cif", ".bcif", ".cif.gz", ".bcif.gz"]):
        file_path = tempfile.NamedTemporaryFile(suffix=file.filename, delete=False).name
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    elif file.filename.endswith(".sdf"):
        sdf_path = tempfile.NamedTemporaryFile(suffix=file.filename, delete=False).name
        with open(sdf_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        pdb_path = sdfToPdb(sdf_path)
        file_path = pdb2cif(pdb_path)
        
    background_tasks.add_task(clean)
    pdbimages = PDBImagesMesh()
    return await pdbimages.GetMeshLocal(file_path)
