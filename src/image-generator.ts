import { Mat3 } from 'molstar/lib/commonjs/mol-math/linear-algebra';
import { ModelSymmetry } from 'molstar/lib/commonjs/mol-model-formats/structure/property/symmetry';
import { Model } from 'molstar/lib/commonjs/mol-model/structure';
import { ROTATION_MATRICES, structureLayingTransform } from 'molstar/lib/commonjs/mol-plugin-state/manager/focus-camera/orient-axes';
import { PluginContext } from 'molstar/lib/commonjs/mol-plugin/context';
import { Color } from 'molstar/lib/commonjs/mol-util/color';

import { DomainRecord, ModifiedResidueRecord, PDBeAPI, PDBeAPIReturn, SiftsSource } from './api';
import { Captions, ImageSpec } from './captions/captions';
import { adjustCamera, changeCameraRotation, combineRotations, zoomAll } from './helpers/camera';
import { ANNOTATION_COLORS, ENTITY_COLORS, MODRES_COLORS, assignEntityAndUnitColors, cycleIterator } from './helpers/colors';
import { getModifiedResidueInfo } from './helpers/helpers';
import { getLogger } from './helpers/logging';
import { countDomains, selectBestChainForDomains, sortDomainsByChain, sortDomainsByEntity } from './helpers/sifts';
import { countChainResidues, getChainInfo, getEntityInfo, getLigandInfo } from './helpers/structure-info';
import { SubstructureDef } from './helpers/substructure-def';
import { ImageType, ImageTypes } from './main';
import { ModelNode, RootNode, StructureNode, TrajectoryNode, VisualNode, using } from './tree-manipulation';


const logger = getLogger(module);

const ALLOW_GHOST_NODES = true; // just for debugging, should be `true` in production
const ALLOW_COLLAPSED_NODES = true; // just for debugging, should be `true` in production

interface DataPromises {
    entityNames?: Promise<PDBeAPIReturn<'getEntityNames'>>;
    preferredAssembly?: Promise<PDBeAPIReturn<'getPreferredAssembly'>>;
    siftsMappings?: Promise<PDBeAPIReturn<'getSiftsMappings'>>;
    modifiedResidues?: Promise<PDBeAPIReturn<'getModifiedResidue'>>;
}


export class ImageGenerator {
    private rotation: Mat3 = Mat3.identity();
    public readonly imageTypes: Set<ImageType>;

    constructor(
        public readonly plugin: PluginContext,
        public readonly saveFunction: (spec: ImageSpec) => any,
        public readonly api: PDBeAPI,
        imageTypes?: ImageType[],
        /** 'front' is to render only front view; 'all' is to render front, side, and top view; 'auto' is to render all three views only for certain image types */
        public views: 'front' | 'all' | 'auto' = 'auto',
    ) {
        if (!imageTypes || imageTypes.includes('all')) {
            this.imageTypes = new Set(ImageTypes);
        } else {
            this.imageTypes = new Set(imageTypes);
        }
    }

    /** Return `true` if any of `imageTypes` is requested to be rendered. */
    private shouldRender(...imageTypes: ImageType[]) {
        return imageTypes.some(t => this.imageTypes.has(t));
    }

    async processAll(url: string, entryId: string, format: 'cif' | 'bcif', mode: 'pdb' | 'alphafold') {
        logger.info('Processing', entryId, 'from', url);
        const startTime = Date.now();
        let success = false;
        try {
            const promises: DataPromises = (mode === 'pdb') ? {
                entityNames: this.api.getEntityNames(entryId),
                preferredAssembly: this.api.getPreferredAssembly(entryId),
                siftsMappings: this.api.getSiftsMappings(entryId),
                modifiedResidues: this.api.getModifiedResidue(entryId),
            } : {}; // allow async fetching in the meantime

            const root = RootNode.create(this.plugin);
            await using(root.makeDownload({ url, isBinary: format === 'bcif' }, entryId), async download => {
                const cif = await download.makeCif();
                const traj = await cif.makeTrajectory();
                await using(traj.makeModel(0), async rawModel => {
                    const model = await rawModel.makeCustomModelProperties(this.api);

                    // Images from deposited model structure
                    await this.processDepositedStructure(mode, entryId, model, traj, promises);

                    // Images from assembly structures
                    if (mode === 'pdb' && this.shouldRender('assembly', 'entity', 'modres')) {
                        const assemblies = ModelSymmetry.Provider.get(model.data!)?.assemblies ?? [];
                        const preferredAssembly = await promises.preferredAssembly;
                        for (const assembly of assemblies) {
                            const isPreferredAssembly = assembly.id === preferredAssembly?.assemblyId;
                            await this.processAssemblyStructure(entryId, model, assembly.id, isPreferredAssembly, promises);
                        }
                    }
                });
            });
            success = true;
        } finally {
            const seconds = (Date.now() - startTime) / 1000;
            logger.info('Processed', entryId, 'in', seconds, 'seconds', success ? '' : '(failed)');
        }
    }

    private async processDepositedStructure(mode: 'pdb' | 'alphafold', entryId: string, model: ModelNode, traj: TrajectoryNode, promises: DataPromises) {
        if (!this.shouldRender('entry', 'validation', 'bfactor', 'ligand', 'domain', 'plddt')) return;

        await using(model.makeStructure({ type: { name: 'model', params: {} } }), async structure => {
            const group = await structure.makeGroup({ label: 'Whole Entry' }, { state: { isGhost: ALLOW_GHOST_NODES } });
            const components = await group.makeStandardComponents();
            const visuals = await components.makeStandardVisuals();
            this.orientAndZoom(structure);
            const nModels = traj.data?.frameCount ?? 1;
            const context = {
                entryId, assemblyId: undefined, isPreferredAssembly: false, nModels,
                entityNames: await promises.entityNames ?? {}, entityInfo: getEntityInfo(structure.data!)
            };
            const colors = assignEntityAndUnitColors(structure.data!);

            if (mode === 'pdb') {
                logger.info('Number of models:', nModels);
                if (this.shouldRender('entry')) {
                    if (nModels === 1) {
                        await visuals.applyToAll(vis => vis.setColorByChainInstance({ colorList: colors.units, entityColorList: colors.entities }));
                        await this.saveViews('all', view => Captions.forEntryOrAssembly({ ...context, coloring: 'chains', view }));

                        await visuals.applyToAll(vis => vis.setColorByEntity({ colorList: colors.entities }));
                        await this.saveViews('all', view => Captions.forEntryOrAssembly({ ...context, coloring: 'entities', view }));
                    } else {
                        model.setCollapsed(ALLOW_COLLAPSED_NODES);
                        await using(traj.makeGroup({ label: 'Other models' }, { state: { isGhost: ALLOW_GHOST_NODES } }), async group => {
                            const allVisuals: (VisualNode | undefined)[] = Object.values(visuals.nodes);
                            for (let iModel = 1; iModel < nModels; iModel++) {
                                const otherModel = await group.makeModel(iModel);
                                const otherStructure = await otherModel.makeStructure({ type: { name: 'model', params: {} } });
                                const otherComponents = await otherStructure.makeStandardComponents();
                                const otherVisuals = await otherComponents.makeStandardVisuals();
                                otherModel.setCollapsed(ALLOW_COLLAPSED_NODES);
                                allVisuals.push(...Object.values(otherVisuals.nodes));
                            }
                            for (const vis of allVisuals) await vis?.setColorByChainInstance();
                            await this.saveViews('all', view => Captions.forEntryOrAssembly({ ...context, coloring: 'chains', view }));

                            for (const vis of allVisuals) await vis?.setColorByEntity();
                            await this.saveViews('all', view => Captions.forEntryOrAssembly({ ...context, coloring: 'entities', view }));
                        });
                        model.setCollapsed(false);
                    }
                }

                if (this.shouldRender('validation')) {
                    await visuals.applyToAll(vis => vis.setColorByGeometryValidation());
                    await this.saveViews('front', view => Captions.forGeometryValidation({ entryId, view }));
                }
                if (this.shouldRender('bfactor')) {
                    if (model.data && Model.isFromXray(model.data)) {
                        await visuals.nodes.polymerCartoon?.setPutty();
                        await visuals.applyToAll(vis => vis.setColorByBfactor('rainbow'));
                        await this.saveViews('front', view => Captions.forBFactor({ entryId, view }));
                        await visuals.nodes.polymerCartoon?.setCartoon();
                    } else {
                        logger.info('Skipping B-factor images because the structure is not from diffraction.');
                    }
                }
                await visuals.applyToAll(vis => vis.setFaded());
                await visuals.applyToAll(vis => vis.setGhost(false));
                await visuals.applyToAll(vis => vis.setCollapsed(ALLOW_COLLAPSED_NODES));
                await visuals.applyToAll(vis => vis.setVisible(false));

                if (this.shouldRender('ligand')) {
                    await this.processLigands(structure, context, colors.entities);
                }
                if (this.shouldRender('domain')) {
                    const siftsMappings = await promises.siftsMappings;
                    if (siftsMappings) {
                        await this.processDomains(structure, siftsMappings, context);
                    }
                }
            }

            if (mode === 'alphafold' && this.shouldRender('plddt')) {
                await visuals.applyToAll(vis => vis.setColorByPlddt());
                await this.saveViews('all', view => Captions.forPlddt({ afdbId: entryId, view }));
            }
        });
    }

    private async processAssemblyStructure(entryId: string, model: ModelNode, assemblyId: string, isPreferredAssembly: boolean, promises: DataPromises) {
        await using(model.makeStructure({ type: { name: 'assembly', params: { id: assemblyId } } }), async structure => {
            const context = {
                entryId, assemblyId, isPreferredAssembly, nModels: 1,
                entityNames: await promises.entityNames ?? {}, entityInfo: getEntityInfo(structure.data!)
            };
            const colors = assignEntityAndUnitColors(structure.data!);
            const group = await structure.makeGroup({ label: 'Whole Assembly' }, { state: { isGhost: ALLOW_GHOST_NODES } });
            const components = await group.makeStandardComponents();
            const visuals = await components.makeStandardVisuals();
            this.orientAndZoom(structure);
            if (this.shouldRender('assembly')) {
                await visuals.applyToAll(vis => vis.setColorByChainInstance({ colorList: colors.units, entityColorList: colors.entities }));
                await this.saveViews('all', view => Captions.forEntryOrAssembly({ ...context, coloring: 'chains', view }));

                await visuals.applyToAll(vis => vis.setColorByEntity({ colorList: colors.entities }));
                await this.saveViews('all', view => Captions.forEntryOrAssembly({ ...context, coloring: 'entities', view }));
            }

            if (isPreferredAssembly) {
                await visuals.applyToAll(vis => vis.setFaded());
                if (this.shouldRender('entity')) {
                    await this.processEntities(structure, context, colors.entities);
                }
                if (this.shouldRender('modres')) {
                    await this.processModifiedResidues(structure, await promises.modifiedResidues ?? [], context);
                }
            }
        });
    }

    private async processEntities(structure: StructureNode, context: Captions.StructureContext, colors: Color[] = ENTITY_COLORS) {
        const { entityInfo, assemblyId } = context;
        await using(structure.makeGroup({ label: 'Entities' }, { state: { isGhost: ALLOW_GHOST_NODES } }), async group => {
            // here it crashes on 7y7a (16GB RAM Mac), FATAL ERROR: Ineffective mark-compacts near heap limit Allocation failed - JavaScript heap out of memory
            const entityStructs = await group.makeEntities(entityInfo);
            for (const [entityId, entityStruct] of Object.entries(entityStructs)) {
                if (!entityStruct) continue;
                const entityColor = colors[entityInfo[entityId].index % colors.length];
                const components = await entityStruct.makeStandardComponents();
                const visuals = await components.makeStandardVisuals();
                await visuals.applyToAll(vis => vis.setHighlight(entityColor));
                entityStruct.setVisible(false);
                entityStruct.setCollapsed(ALLOW_COLLAPSED_NODES);
            }
            for (const [entityId, entityStruct] of Object.entries(entityStructs)) {
                if (entityInfo[entityId].type === 'water') {
                    logger.info(`Skipping images for entity ${entityId} (water entity)`);
                    continue;
                }
                if (!entityStruct) {
                    const assembly = assemblyId ? `assembly ${assemblyId}` : 'the model';
                    logger.warn(`Skipping images for entity ${entityId} (not present in ${assembly})`);
                    continue;
                }
                entityStruct.setVisible(true);
                await this.saveViews('all', view => Captions.forHighlightedEntity({ ...context, entityId, view }));
                entityStruct.setVisible(false);
            }
        });
    }

    private async processLigands(structure: StructureNode, context: Captions.StructureContext, entityColors?: Color[]) {
        const structData = structure.data!;
        const ligandInfo = getLigandInfo(structData);
        for (const info of Object.values(ligandInfo)) {
            await using(structure.makeLigEnvComponents(info, { state: { isCollapsed: ALLOW_COLLAPSED_NODES } }), async components => {
                const visuals = await components.makeLigEnvVisuals(entityColors);
                this.orientAndZoom(components.nodes.ligand!);
                await this.saveViews('front', view => Captions.forLigandEnvironment({ ...context, view, ligandInfo: info }));
            });
        }
    }

    private async processDomains(structure: StructureNode, domains: { [source in SiftsSource]: { [family: string]: DomainRecord[] } }, context: Captions.StructureContext) {
        const chainInfo = getChainInfo(structure.data!.model);
        const chainCoverages = countChainResidues(structure.data!.model);

        const allDomains = sortDomainsByEntity(domains);
        const selectedDomains = selectBestChainForDomains(allDomains, chainCoverages);
        const selectedDomainsByChain = sortDomainsByChain(selectedDomains);
        const allDomainCounts = countDomains(allDomains);
        const selectedDomainCounts = countDomains(selectedDomains);

        const colorsIterator = cycleIterator(ANNOTATION_COLORS);
        for (const [chainId, chainDomains] of Object.entries(selectedDomainsByChain)) {
            const authChainId = chainInfo[chainId].authChainId;
            await using(structure.makeAuthChain(authChainId, chainId), async chain => { // selecting by authChainId to include ligands
                if (!chain) return;
                const entityId = chainInfo[chainId].entityId;
                const components = await chain.makeStandardComponents();
                const visuals = await components.makeStandardVisuals();
                this.orientAndZoom(chain);
                await visuals.applyToAll(vis => vis.setFaded());

                for (const [source, sourceDomains] of Object.entries(chainDomains)) {
                    for (const [familyId, familyDomains] of Object.entries(sourceDomains)) {
                        const domDefs: { [id: string]: SubstructureDef } = {};
                        for (const dom of familyDomains) {
                            const label = `Domain ${dom.id} (${source} ${familyId})`;
                            const ranges = dom.chunks.map(c => [c.startResidue, c.endResidue] as [number, number]);
                            domDefs[dom.id] = SubstructureDef.Domain.create(chainId, ranges, label);
                        }
                        const familyName = familyDomains[0].familyName;
                        const totalCopies = allDomainCounts[source][familyId][entityId];
                        const shownCopies = selectedDomainCounts[source][familyId][entityId];
                        await using(structure.makeGroup({ label: 'Domains' }, { state: { isGhost: ALLOW_GHOST_NODES } }), async group => {
                            const domainStructures = await group.makeSubstructures(domDefs);
                            const outOfRangeCopies = shownCopies - Object.keys(domainStructures).length; // this will be >0 when a domain is out of observed residue ranges (e.g. 8eiu chain KA [auth h] Pfam PF03948)
                            for (const domainStruct of Object.values(domainStructures)) {
                                const components = await domainStruct.makeStandardComponents();
                                const visuals = await components.makeStandardVisuals();
                                const color = colorsIterator.next().value!; // same color for all visual of the domain
                                await visuals.applyToAll(vis => vis.setColorUniform(color));
                            }
                            await this.saveViews('front', view => Captions.forDomain({ ...context, source, familyId, familyName, entityId, chainId, authChainId, totalCopies, shownCopies, outOfRangeCopies, view }));
                        });
                    };
                };
            });
        };
    }

    private async processModifiedResidues(structure: StructureNode, modifiedResidues: ModifiedResidueRecord[], context: Captions.StructureContext) {
        if (modifiedResidues.length === 0) {
            return;
        }
        const modresInfo = getModifiedResidueInfo(modifiedResidues);
        const setDefinitions: { [modres: string]: SubstructureDef } = {};
        for (const modres in modresInfo) setDefinitions[modres] = modresInfo[modres].instances;

        const colorsIterator = cycleIterator(MODRES_COLORS);
        await using(structure.makeGroup({ label: 'Modified Residues' }, { state: { isGhost: ALLOW_GHOST_NODES } }), async group => {
            const modresStructures = await group.makeSubstructures(setDefinitions);
            for (const struct of Object.values(modresStructures)) {
                const visual = await struct.makeBallsAndSticks(['modresSticks']);
                await visual.setHighlight(colorsIterator.next().value!);
                struct.setCollapsed(ALLOW_COLLAPSED_NODES);
                struct.setVisible(false);
            }
            for (const [modres, struct] of Object.entries(modresStructures)) {
                const nInstances = struct.data!.atomicResidueCount; // Using number of instances in the assembly, not in the deposited model
                struct.setVisible(true);
                await this.saveViews('all', view => Captions.forModifiedResidue({ ...context, modresInfo: { ...modresInfo[modres], nInstances }, view }));
                struct.setVisible(false);
            };
        });
    }

    private orientAndZoom(structure: StructureNode, referenceRotation?: Mat3) {
        this.rotation = structureLayingTransform([structure.data!], referenceRotation).rotation;
        zoomAll(this.plugin);
    }

    private async saveViews(views: 'front' | 'all', spec: (view: 'front' | 'side' | 'top' | undefined) => ImageSpec) {
        if (this.views === 'all' || (this.views === 'auto' && views === 'all')) {
            adjustCamera(this.plugin, s => changeCameraRotation(s, this.rotation));
            await this.saveFunction(spec('front'));

            const rotationSide = combineRotations(this.rotation, ROTATION_MATRICES.rotY270);
            adjustCamera(this.plugin, s => changeCameraRotation(s, rotationSide));
            await this.saveFunction(spec('side'));

            const rotationTop = combineRotations(this.rotation, ROTATION_MATRICES.rotX90);
            adjustCamera(this.plugin, s => changeCameraRotation(s, rotationTop));
            await this.saveFunction(spec('top'));
        } else {
            adjustCamera(this.plugin, s => changeCameraRotation(s, this.rotation));
            await this.saveFunction(spec(undefined));
        }
    }
}
