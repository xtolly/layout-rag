/**
 * 智能元件布局系统 — 前端逻辑
 * 
 * 模块职责划分：
 *   API          – 与后端通信的封装函数
 *   State        – Vue 响应式状态声明
 *   History      – 撤销/重做记录管理
 *   File         – 文件上传处理
 *   Preview      – 推荐列表缩略预览计算
 *   Canvas View  – 双画板的缩放/平移逻辑
 *   Drag & Drop  – 元件拖拽微调 + 吸附 + 防重叠
 *   Layout Apply – 应用模板 & 数据映射
 *   Submit       – 最终布局提交
 */

const { createApp, ref, computed, reactive, onMounted, onUnmounted, nextTick } = Vue;

const DEFAULT_UNKNOWN_COLOR = 'hsl(215, 16%, 55%)';
const API_BASE_URL = `${window.location.origin}/api`;

// ============================================================
//  API 层
// ============================================================

async function apiGet(path) {
    const res = await fetch(`${API_BASE_URL}${path}`);
    if (!res.ok) throw new Error(`${path} 请求失败: ${res.statusText}`);
    return res.json();
}

async function apiPost(path, body) {
    const res = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${path} 请求失败: ${res.statusText}`);
    return res.json();
}

// ============================================================
//  Vue 应用
// ============================================================

const App = {
    setup() {

        // ── 全局流程状态 ──────────────────────────────────────
        const step        = ref(0);
        const isLoading   = ref(false);
        const loadingText = ref('');

        // ── 业务数据 ──────────────────────────────────────────
        const originalUploadJson     = ref(null);
        const recommendedTemplates   = ref([]);
        const previewTemplate        = ref(null);
        const featureSchema          = ref({});
        const partColorMap           = ref({});
        const unknownPartColor       = ref(DEFAULT_UNKNOWN_COLOR);

        const uploadDataMeta     = computed(() => originalUploadJson.value?.scheme);
        const totalFeatureCount  = computed(() => {
            const schemaCount = Object.keys(featureSchema.value || {}).length;
            if (schemaCount > 0) return schemaCount;
            return recommendedTemplates.value?.[0]?.featureDiffs?.length || 0;
        });

        // ── 模板画板状态 ──────────────────────────────────────
        const tplPanelSize       = ref([600, 1600]);
        const tplPanelType       = ref('安装板');
        const tplPlacedParts     = ref([]);
        const tplCanvasScale     = ref(1);
        const tplPanX            = ref(0);
        const tplPanY            = ref(0);
        const tplCanvasContainer = ref(null);

        // ── 预览模态画板状态 ──────────────────────────────────
        const previewPanelSize       = computed(() => previewTemplate.value?.scheme?.panel_size || previewTemplate.value?.meta?.panel_size || [600, 1600]);
        const previewCanvasScale     = ref(1);
        const previewPanX            = ref(0);
        const previewPanY            = ref(0);
        const previewCanvasContainer = ref(null);
        const previewOnlyDiffs       = ref(true);

        // ── 项目画板状态 ──────────────────────────────────────
        const prjPanelSize       = ref([600, 1600]);
        const prjPanelType       = ref('安装板');
        const placedParts        = ref([]);
        const prjCanvasScale     = ref(1);
        const prjPanX            = ref(0);
        const prjPanY            = ref(0);
        const prjCanvasContainer = ref(null);
        const panelRef           = ref(null);

        // ── 多面板只读状态 ────────────────────────────────────
        const multiPanels         = ref([]); // [{panelSize, panelType, parts}]
        const isMultiPanelMode    = computed(() => multiPanels.value.length > 1);
        const multiPanelTotalSize = computed(() => {
            const ps = multiPanels.value;
            if (!ps.length) return [600, 1600];
            const totalW = ps.reduce((s, p) => s + p.panelSize[0], 0) + 500 * (ps.length - 1);
            return [totalW, Math.max(...ps.map(p => p.panelSize[1]))];
        });
        const getPanelOffset = (idx) => {
            let offset = 0;
            for (let i = 0; i < idx; i++) offset += multiPanels.value[i].panelSize[0] + 500;
            return offset;
        };

        // ── 选配布局模式状态 ──────────────────────────────────
        const isLayoutPanelMode = ref(false);
        const isManualLayoutMode = ref(false);
        const layoutPanelSource = ref(null);
        const workbenchMode = ref('layout'); // 'recommend' | 'layout' | 'view'
        // ── 全局交互状态 ──────────────────────────────────────
        const settings     = reactive({ autoSnap: true, autoExtrude: true });
        const isDragging   = ref(false);
        const fileInput    = ref(null);
        const isPanning    = ref(false);
        const isSpaceDown  = ref(false);
        const activePanView = ref(null); // 'tpl' | 'prj' | 'preview'
        let panStartX = 0, panStartY = 0;

        const epsilon = 1e-4; // 屏蔽浮点运算导致的虚假碰撞

        // ============================================================
        //  History – 撤销/重做
        // ============================================================

        const history      = ref([]);
        const historyIndex = ref(-1);
        const MAX_HISTORY  = 50;

        const getCurrentStateStr = () => JSON.stringify({ placed: placedParts.value });

        const saveHistory = () => {
            const cur = getCurrentStateStr();
            if (historyIndex.value >= 0 && cur === JSON.stringify(history.value[historyIndex.value])) return;
            if (historyIndex.value < history.value.length - 1)
                history.value = history.value.slice(0, historyIndex.value + 1);
            history.value.push(JSON.parse(cur));
            if (history.value.length > MAX_HISTORY) history.value.shift(); else historyIndex.value++;
        };

        const restoreState = (state) => { placedParts.value = JSON.parse(JSON.stringify(state.placed)); checkBounds(); };
        const canUndo = computed(() => historyIndex.value > 0);
        const canRedo = computed(() => historyIndex.value < history.value.length - 1);
        const undo = () => { if (!canUndo.value) return; historyIndex.value--; restoreState(history.value[historyIndex.value]); };
        const redo = () => { if (!canRedo.value) return; historyIndex.value++; restoreState(history.value[historyIndex.value]); };

        // ============================================================
        //  颜色映射
        // ============================================================

        const getColor = (type) => {
            const t = typeof type === 'string' ? type.trim() : '';
            return t ? (partColorMap.value[t] || unknownPartColor.value) : unknownPartColor.value;
        };

        const loadPartColorMap = async () => {
            try {
                const payload = await apiGet('/part-color-map');
                partColorMap.value    = payload.partColorMap || {};
                unknownPartColor.value = payload.unknownColor || DEFAULT_UNKNOWN_COLOR;
            } catch (e) {
                console.warn('元件颜色映射加载失败:', e);
            }
        };

        // ============================================================
        //  文件上传 & 推荐
        // ============================================================

        const triggerFileInput = () => fileInput.value.click();
        const handleFileDrop   = (e) => { isDragging.value = false; if (e.dataTransfer.files.length) processFile(e.dataTransfer.files[0]); };
        const handleFileSelect = (e) => { if (e.target.files.length) processFile(e.target.files[0]); e.target.value = ''; };

        const processFile = (file) => {
            if (!file.name.endsWith('.json')) return alert('仅支持上传 JSON 文件');
            const reader = new FileReader();
            reader.onload = async (ev) => {
                try {
                    const json = JSON.parse(ev.target.result);
                    if (!json.scheme || !json.scheme.parts) throw new Error('JSON 格式缺少 scheme 或 parts 节点');
                    originalUploadJson.value = json;
                    isLoading.value = true;
                    loadingText.value = '正在进行特征匹配...';

                    if (!Object.keys(featureSchema.value).length)
                        featureSchema.value = await apiGet('/schema');

                    const res = await apiPost('/recommend', json);
                    recommendedTemplates.value = res.templates;
                    step.value = 2;
                } catch (err) {
                    alert('操作失败: ' + err.message);
                } finally {
                    isLoading.value = false;
                }
            };
            reader.readAsText(file);
        };

        // ============================================================
        //  推荐列表缩略预览
        // ============================================================

        const getPreviewPanelStyle = (size) => {
            if (!size) return {};
            const maxW = 200, maxH = 185;
            const scale = Math.min(maxW / size[0], maxH / size[1]);
            return { width: Math.round(size[0] * scale) + 'px', height: Math.round(size[1] * scale) + 'px' };
        };

        const getPreviewInnerStyle = (size) => {
            if (!size) return {};
            const maxW = 200, maxH = 185;
            const scale = Math.min(maxW / size[0], maxH / size[1]);
            return { width: size[0] + 'px', height: size[1] + 'px', transform: `scale(${scale})`, transformOrigin: 'top left' };
        };

        const getPreviewParts = (tpl) => {
            const info = {};
            const schemeData = tpl.scheme || tpl.meta || {};
            if (schemeData.parts) {
                schemeData.parts.forEach(p => {
                    if (tpl.arrange?.[p.part_id]) {
                        const entry = { part_type: p.part_type, part_size: p.part_size, position: tpl.arrange[p.part_id].position };
                        if (p.parts && p.parts.length) { entry.parts = p.parts; entry.arrange = p.arrange; }
                        info[p.part_id] = entry;
                    }
                });
            }
            return info;
        };

        const openTemplatePreview  = (tpl) => { previewTemplate.value = tpl; previewOnlyDiffs.value = true; nextTick(() => resetView('preview')); };
        const closeTemplatePreview = ()    => { previewTemplate.value = null; previewOnlyDiffs.value = true; };

        const previewFeatureDiffs = computed(() => {
            const diffs = previewTemplate.value?.featureDiffs || [];
            return previewOnlyDiffs.value ? diffs.filter(f => f.status !== 'green') : diffs;
        });

        // ============================================================
        //  画板视图控制 – 缩放 & 平移
        // ============================================================

        const resetSpecificView = (containerRef, sizeRef, scaleRef, panXRef, panYRef, padding = { x: 60, y: 120 }) => {
            if (!containerRef.value) return;
            const rect = containerRef.value.getBoundingClientRect();
            const scale = Math.min((rect.width - padding.x) / sizeRef.value[0], (rect.height - padding.y) / sizeRef.value[1]);
            scaleRef.value = scale;
            panXRef.value = (rect.width  - sizeRef.value[0] * scale) / 2;
            panYRef.value = (rect.height - sizeRef.value[1] * scale) / 2;
        };

        const resetView = (viewStr) => {
            if (viewStr === 'tpl'     || !viewStr) resetSpecificView(tplCanvasContainer,     tplPanelSize,     tplCanvasScale,     tplPanX,     tplPanY);
            if (viewStr === 'prj'     || !viewStr) resetSpecificView(prjCanvasContainer, isMultiPanelMode.value ? multiPanelTotalSize : prjPanelSize, prjCanvasScale, prjPanX, prjPanY);
            if (viewStr === 'preview' || !viewStr) resetSpecificView(previewCanvasContainer, previewPanelSize, previewCanvasScale, previewPanX, previewPanY, { x: 40, y: 40 });
        };

        const _resolveRefs = (viewStr) => {
            const isTpl = viewStr === 'tpl', isPrev = viewStr === 'preview';
            return {
                scaleRef:     isTpl ? tplCanvasScale     : (isPrev ? previewCanvasScale     : prjCanvasScale),
                panXRef:      isTpl ? tplPanX            : (isPrev ? previewPanX            : prjPanX),
                panYRef:      isTpl ? tplPanY            : (isPrev ? previewPanY            : prjPanY),
                containerRef: isTpl ? tplCanvasContainer : (isPrev ? previewCanvasContainer : prjCanvasContainer),
            };
        };

        const handleWheel = (e, viewStr) => {
            const { scaleRef, panXRef, panYRef, containerRef } = _resolveRefs(viewStr);
            const direction = e.deltaY < 0 ? 1 : -1;
            let newScale = scaleRef.value * (direction > 0 ? 1.1 : 1 / 1.1);
            newScale = Math.max(0.1, Math.min(newScale, 5));
            const rect = containerRef.value.getBoundingClientRect();
            const mouseX = e.clientX - rect.left, mouseY = e.clientY - rect.top;
            panXRef.value = mouseX - (mouseX - panXRef.value) * (newScale / scaleRef.value);
            panYRef.value = mouseY - (mouseY - panYRef.value) * (newScale / scaleRef.value);
            scaleRef.value = newScale;
        };

        const startPan = (e, viewStr) => {
            const allowPan = viewStr === 'preview'
                ? (e.button === 0 || e.button === 1)
                : (e.button === 1 || (e.button === 0 && isSpaceDown.value));
            if (!allowPan) return;
            e.preventDefault();
            isPanning.value    = true;
            activePanView.value = viewStr;
            const { panXRef, panYRef } = _resolveRefs(viewStr);
            panStartX = e.clientX - panXRef.value;
            panStartY = e.clientY - panYRef.value;
            document.addEventListener('mousemove', onPanMove);
            document.addEventListener('mouseup', endPan);
        };

        const onPanMove = (e) => {
            if (!isPanning.value || !activePanView.value) return;
            const { panXRef, panYRef } = _resolveRefs(activePanView.value);
            panXRef.value = e.clientX - panStartX;
            panYRef.value = e.clientY - panStartY;
        };

        const endPan = () => {
            isPanning.value = false;
            activePanView.value = null;
            document.removeEventListener('mousemove', onPanMove);
            document.removeEventListener('mouseup', endPan);
        };

        // ============================================================
        //  键盘快捷键
        // ============================================================

        const handleKeydown = (e) => {
            if (step.value !== 3) return;
            if (e.code === 'Space') { isSpaceDown.value = true; e.preventDefault(); }
            if (e.ctrlKey || e.metaKey) {
                if (e.key === 'z' || e.key === 'Z') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
                else if (e.key === 'y' || e.key === 'Y') { e.preventDefault(); redo(); }
            }
        };
        const handleKeyup = (e) => { if (e.code === 'Space') isSpaceDown.value = false; };

        onMounted(() => {
            window.addEventListener('keydown', handleKeydown);
            window.addEventListener('keyup', handleKeyup);
            loadPartColorMap();

            // 始终以嵌入模式运行，监听父窗口消息
            window.addEventListener('message', (e) => {
                if (e.origin !== window.location.origin) return;
                const { type, payload, workbenchMode: wbMode } = e.data || {};
                if (wbMode) workbenchMode.value = wbMode;
                if (type === 'init:layoutPanel') {
                    initLayoutPanelMode(payload);
                } else if (type === 'init:layoutPanelManual') {
                    initManualLayoutMode(payload);
                } else if (type === 'workbench:requestBack') {
                    if (step.value === 3) goBackToRecommend();
                    else goBackToConfig();
                } else if (type === 'workbench:requestSubmit') {
                    submitLayoutPanel();
                }
            });
            window.parent.postMessage({ type: 'workbench:ready' }, window.location.origin);
        });
        onUnmounted(() => {
            window.removeEventListener('keydown', handleKeydown);
            window.removeEventListener('keyup', handleKeyup);
        });

        // ============================================================
        //  元件拖拽微调
        // ============================================================

        const activeGuides   = ref([]);
        let currentDragPart  = null;
        let dragOffset       = [0, 0];

        const hasInvalid = computed(() => placedParts.value.some(p => p.isInvalid));
        const checkBounds = () => {
            placedParts.value.forEach(part => {
                const [x, y] = part.position, [w, h] = part.part_size, [pw, ph] = prjPanelSize.value;
                part.isInvalid = (x < 0 || y < 0 || x + w > pw + epsilon || y + h > ph + epsilon);
            });
        };

        const getViewportGuides = (dragPart) => {
            const guides = { xEdges: [], xCenters: [], yEdges: [], yCenters: [] };
            const [pw, ph] = prjPanelSize.value;
            guides.xEdges.push(0, pw); guides.xCenters.push(pw / 2);
            guides.yEdges.push(0, ph); guides.yCenters.push(ph / 2);

            if (!prjCanvasContainer.value) return guides;
            const rect  = prjCanvasContainer.value.getBoundingClientRect();
            const scale = prjCanvasScale.value;
            const buf   = 50 / scale;
            const vL = -prjPanX.value / scale - buf, vT = -prjPanY.value / scale - buf;
            const vR = (rect.width  - prjPanX.value) / scale + buf;
            const vB = (rect.height - prjPanY.value) / scale + buf;

            placedParts.value.forEach(p => {
                if (p.part_id === dragPart.part_id) return;
                const [px, py] = p.position, [pW, pH] = p.part_size;
                if (px + pW >= vL && px <= vR && py + pH >= vT && py <= vB) {
                    guides.xEdges.push(px, px + pW); guides.xCenters.push(px + pW / 2);
                    guides.yEdges.push(py, py + pH); guides.yCenters.push(py + pH / 2);
                }
            });
            guides.xEdges    = [...new Set(guides.xEdges)];
            guides.xCenters  = [...new Set(guides.xCenters)];
            guides.yEdges    = [...new Set(guides.yEdges)];
            guides.yCenters  = [...new Set(guides.yCenters)];
            return guides;
        };

        const startMove = (e, part) => {
            if (isSpaceDown.value || e.button !== 0) return;
            e.stopPropagation();
            currentDragPart = part;
            const rect = panelRef.value.getBoundingClientRect();
            dragOffset = [
                ((e.clientX - rect.left) / prjCanvasScale.value) - part.position[0],
                ((e.clientY - rect.top)  / prjCanvasScale.value) - part.position[1],
            ];
            document.addEventListener('mousemove', onMovePart);
            document.addEventListener('mouseup', endMovePart);
        };

        const onMovePart = (e) => {
            if (!currentDragPart) return;
            const rect  = panelRef.value.getBoundingClientRect();
            const scale = prjCanvasScale.value;
            let tx = ((e.clientX - rect.left) / scale) - dragOffset[0];
            let ty = ((e.clientY - rect.top)  / scale) - dragOffset[1];
            activeGuides.value = [];

            if (settings.autoSnap) {
                const guides = getViewportGuides(currentDragPart);
                const [w, h] = currentDragPart.part_size;
                const thresh = 10 / scale;
                const myXEdges  = [tx, tx + w],   myXCenter = tx + w / 2;
                const myYEdges  = [ty, ty + h],   myYCenter = ty + h / 2;
                let bX = { delta: thresh, linePos: null }, bY = { delta: thresh, linePos: null };

                guides.xEdges.forEach(gx => myXEdges.forEach(mx => { const d = gx - mx; if (Math.abs(d) < Math.abs(bX.delta)) bX = { delta: d, linePos: gx }; }));
                guides.xCenters.forEach(gxc => { const d = gxc - myXCenter; if (Math.abs(d) < Math.abs(bX.delta)) bX = { delta: d, linePos: gxc }; });
                guides.yEdges.forEach(gy => myYEdges.forEach(my => { const d = gy - my; if (Math.abs(d) < Math.abs(bY.delta)) bY = { delta: d, linePos: gy }; }));
                guides.yCenters.forEach(gyc => { const d = gyc - myYCenter; if (Math.abs(d) < Math.abs(bY.delta)) bY = { delta: d, linePos: gyc }; });

                if (bX.linePos !== null) { tx += bX.delta; activeGuides.value.push({ style: `left:${bX.linePos}px;top:0;bottom:0;width:1px;transform:scaleX(${1/scale});transform-origin:left;` }); }
                if (bY.linePos !== null) { ty += bY.delta; activeGuides.value.push({ style: `top:${bY.linePos}px;left:0;right:0;height:1px;transform:scaleY(${1/scale});transform-origin:top;` }); }
            }
            currentDragPart.position = [Math.round(tx), Math.round(ty)];
        };

        const endMovePart = () => {
            document.removeEventListener('mousemove', onMovePart);
            document.removeEventListener('mouseup', endMovePart);
            activeGuides.value = [];
            if (currentDragPart) {
                if (settings.autoExtrude) resolveOverlaps(currentDragPart);
                checkBounds(); saveHistory(); currentDragPart = null;
            }
        };

        // ============================================================
        //  防重叠挤出算法
        // ============================================================

        const isOverlap = (p1, p2) =>
            !(p1.position[0] + p1.part_size[0] <= p2.position[0] ||
              p1.position[0] >= p2.position[0] + p2.part_size[0] ||
              p1.position[1] + p1.part_size[1] <= p2.position[1] ||
              p1.position[1] >= p2.position[1] + p2.part_size[1]);

        const resolveOverlaps = (movedPart) => {
            const queue = [{ part: movedPart, dir: null }];
            let count = 0;
            while (queue.length > 0 && count++ < 1000) {
                const { part: source, dir: sourceDir } = queue.shift();
                const sL = source.position[0], sT = source.position[1];
                const sR = sL + source.part_size[0], sB = sT + source.part_size[1];

                for (const target of placedParts.value) {
                    if (source.part_id === target.part_id) continue;
                    const tL = target.position[0], tT = target.position[1];
                    const tR = tL + target.part_size[0], tB = tT + target.part_size[1];
                    const oRight = sR - tL, oLeft = tR - sL, oDown = sB - tT, oUp = tB - sT;

                    if (oRight <= epsilon || oLeft <= epsilon || oDown <= epsilon || oUp <= epsilon) continue;

                    let applyDir = sourceDir;
                    if (!applyDir) {
                        const minO = Math.min(oRight, oLeft, oDown, oUp);
                        applyDir = minO === oRight ? 'RIGHT' : minO === oLeft ? 'LEFT' : minO === oDown ? 'DOWN' : 'UP';
                    }

                    const oX = Math.min(oRight, oLeft), oY = Math.min(oDown, oUp);
                    if ((applyDir === 'UP' || applyDir === 'DOWN') && oX <= 1) continue;
                    if ((applyDir === 'LEFT' || applyDir === 'RIGHT') && oY <= 1) continue;

                    if      (applyDir === 'RIGHT') target.position[0] = sR;
                    else if (applyDir === 'LEFT' ) target.position[0] = sL - target.part_size[0];
                    else if (applyDir === 'DOWN' ) target.position[1] = sB;
                    else if (applyDir === 'UP'   ) target.position[1] = sT - target.part_size[1];

                    queue.push({ part: target, dir: applyDir });
                }
            }
            if (count >= 1000) console.warn('触发极限迭代保护，元件可能已经超出画板。');
        };

        // ============================================================
        //  应用模板
        // ============================================================

        const applyTemplate = async (tpl) => {
            isLoading.value = true; loadingText.value = '正在进行约束求解，请稍等...';
            try {
                closeTemplatePreview();
                const otherTemplateUuids = recommendedTemplates.value
                    .filter(c => c.uuid !== tpl.uuid)
                    .map(c => c.uuid);

                const jsonRes = await apiPost('/apply', {
                    template_uuid: tpl.uuid,
                    other_template_uuids: otherTemplateUuids,
                    project_data: originalUploadJson.value,
                });

                const tplData = jsonRes.template_data;
                const prjData = jsonRes.project_data;
                originalUploadJson.value = prjData;

                // 模板画板
                tplPanelSize.value = tplData.scheme.panel_size || [600, 1600];
                tplPanelType.value = tplData.scheme.panel_type || '安装板';
                tplPlacedParts.value = tplData.scheme.parts
                    .filter(p => tplData.arrange?.[p.part_id])
                    .map(p => ({ part_id: p.part_id, part_type: p.part_type, part_size: p.part_size, position: tplData.arrange[p.part_id].position, ...(p.parts?.length ? { parts: p.parts, arrange: p.arrange } : {}) }));

                // 项目画板
                if (Array.isArray(prjData)) {
                    multiPanels.value = prjData.map(item => ({
                        panelSize: item.scheme?.panel_size || [600, 1600],
                        panelType: item.scheme?.panel_type || '安装板',
                        parts: (item.scheme?.parts || []).map(p => ({
                            part_id:   p.part_id,
                            part_type: p.part_type,
                            part_size: p.part_size,
                            position:  item.arrange?.[p.part_id]?.position
                                       ? [...item.arrange[p.part_id].position]
                                       : [0, 0],
                            ...(p.parts?.length ? { parts: p.parts, arrange: p.arrange } : {}),
                        })),
                    }));
                    prjPanelSize.value = multiPanels.value[0]?.panelSize || [600, 1600];
                    prjPanelType.value = multiPanels.value[0]?.panelType || '安装板';
                    placedParts.value  = [];
                } else {
                    multiPanels.value = [];
                    prjPanelSize.value = prjData.scheme.panel_size || [600, 1600];
                    prjPanelType.value = prjData.scheme.panel_type || '安装板';
                    placedParts.value  = prjData.scheme.parts.map(p => ({
                        part_id: p.part_id, part_type: p.part_type, part_size: p.part_size,
                        position: prjData.arrange?.[p.part_id]?.position || [0, 0],
                        isInvalid: false,
                        ...(p.parts?.length ? { parts: p.parts, arrange: p.arrange } : {}),
                    }));
                }

                step.value = 3;
                checkBounds(); history.value = []; historyIndex.value = -1; saveHistory();
                nextTick(() => { resetView('tpl'); resetView('prj'); });
            } catch (err) {
                alert('布局获取失败: ' + err.message);
            } finally {
                isLoading.value = false;
            }
        };

        const goBackToRecommend = () => {
            if (canUndo.value && !confirm('当前项目布局已有修改，返回将丢失这些修改，是否继续？')) return;
            step.value = 2;
        };

        const goBackToConfig = () => {
            window.parent.postMessage({ type: 'workbench:close' }, window.location.origin);
        };

        const closeWorkbench = () => {
            window.parent.postMessage({ type: 'workbench:close' }, window.location.origin);
        };

        const initLayoutPanelMode = async (layoutJson) => {
            isLayoutPanelMode.value = true;
            layoutPanelSource.value = layoutJson;
            try {
                originalUploadJson.value = layoutJson;
                isLoading.value = true;
                loadingText.value = '正在进行特征匹配...';

                if (!Object.keys(featureSchema.value).length)
                    featureSchema.value = await apiGet('/schema');

                const res = await apiPost('/recommend', layoutJson);
                recommendedTemplates.value = res.templates;
                step.value = 2; // 直接进入方案推荐页面
            } catch (err) {
                alert('操作失败: ' + err.message);
                window.parent.postMessage({ type: 'workbench:close' }, window.location.origin);
            } finally {
                isLoading.value = false;
            }
        };

        const initManualLayoutMode = (layoutJson) => {
            // 多面板只读模式
            if (Array.isArray(layoutJson)) {
                isLayoutPanelMode.value = true;
                isManualLayoutMode.value = true;
                multiPanels.value = layoutJson.map(item => ({
                    panelSize: item.scheme?.panel_size || [600, 1600],
                    panelType: item.scheme?.panel_type || '安装板',
                    parts: (item.scheme?.parts || []).map(p => ({
                        part_id:   p.part_id,
                        part_type: p.part_type,
                        part_size: p.part_size,
                        position:  item.arrange?.[p.part_id]?.position
                                   ? [...item.arrange[p.part_id].position]
                                   : [0, 0],
                        ...(p.parts?.length ? { parts: p.parts, arrange: p.arrange } : {}),
                    })),
                }));
                step.value = 3;
                history.value = []; historyIndex.value = -1;
                nextTick(() => resetView('prj'));
                return;
            }

            isLayoutPanelMode.value = true;
            isManualLayoutMode.value = true;
            layoutPanelSource.value = layoutJson;
            originalUploadJson.value = layoutJson;

            const panelSize = layoutJson.scheme?.panel_size || [600, 1600];
            const panelType = layoutJson.scheme?.panel_type || '安装板';
            const parts     = layoutJson.scheme?.parts || [];
            const arrange   = layoutJson.arrange || {};

            // 无模板参考，左侧画板置空
            tplPanelSize.value    = panelSize;
            tplPanelType.value    = panelType;
            tplPlacedParts.value  = [];

            // 右侧项目画板：使用已有 arrange 或默认 [0,0]
            prjPanelSize.value = panelSize;
            prjPanelType.value = panelType;
            placedParts.value  = parts.map(p => ({
                part_id:   p.part_id,
                part_type: p.part_type,
                part_size: p.part_size,
                position:  arrange[p.part_id]?.position ? [...arrange[p.part_id].position] : [0, 0],
                isInvalid: false,
                ...(p.parts?.length ? { parts: p.parts, arrange: p.arrange } : {}),
            }));

            step.value = 3;
            history.value = []; historyIndex.value = -1; saveHistory();
            nextTick(() => resetView('prj'));
        };

        // ============================================================
        //  提交
        // ============================================================

        const submitLayout = async () => {
            if (hasInvalid.value) return alert('存在超出边界的无效元件，无法提交！');
            const output = JSON.parse(JSON.stringify(originalUploadJson.value));
            if (!output.arrange) output.arrange = {};
            placedParts.value.forEach(p => { output.arrange[p.part_id] = { position: p.position, rotation: 0 }; });
            try {
                isLoading.value = true; loadingText.value = '正在提交最终布局数据...';
                await apiPost('/submit', output);
                console.log('最终提交的JSON:', output);
                alert('布局提交成功！完整的 JSON 数据已传输至后端并打印至控制台 (F12)。');
            } catch (err) {
                alert(err.message);
            } finally {
                isLoading.value = false;
            }
        };

        const submitLayoutPanel = () => {
            if (step.value !== 3) return;
            if (hasInvalid.value) return alert('存在超出边界的无效元件，无法提交！');
            
            const exportData = JSON.parse(JSON.stringify(originalUploadJson.value));
            exportData.arrange = {};
            placedParts.value.forEach(p => { 
                exportData.arrange[p.part_id] = { position: [p.position[0], p.position[1]], rotation: 0 }; 
            });

            const result = { scheme: exportData.scheme, arrange: exportData.arrange };
            window.parent.postMessage({ type: 'workbench:layoutPanelResult', payload: JSON.parse(JSON.stringify(result)) }, window.location.origin);
        };

        // ============================================================
        //  工具函数
        // ============================================================

        const formatValue       = (val) => typeof val === 'number' ? Number(val.toFixed(2)) : val;
        const getScoreBadgeClass = (score) =>
            score >= 80 ? 'bg-green-50 text-green-700 border-green-200' :
            score >= 60 ? 'bg-yellow-50 text-yellow-700 border-yellow-200' :
                          'bg-red-50 text-red-600 border-red-200';

        // ============================================================
        //  返回给模板的所有绑定
        // ============================================================

        return {
            // 流程
            step, isLoading, loadingText, isDragging, fileInput,
            // 模式
            isLayoutPanelMode, isManualLayoutMode, workbenchMode,
            // 提交与返回
            goBackToConfig, closeWorkbench, submitLayoutPanel,
            // 数据
            originalUploadJson, recommendedTemplates, previewTemplate, previewOnlyDiffs,
            uploadDataMeta, totalFeatureCount,
            // 模板画板
            tplPanelSize, tplPanelType, tplPlacedParts, tplCanvasScale, tplPanX, tplPanY, tplCanvasContainer,
            // 预览画板
            previewPanelSize, previewCanvasScale, previewPanX, previewPanY, previewCanvasContainer, previewFeatureDiffs,
            // 项目画板
            prjPanelSize, prjPanelType, placedParts, prjCanvasScale, prjPanX, prjPanY, prjCanvasContainer,
            // 交互
            settings, isPanning, isSpaceDown, activePanView,
            // 方法
            triggerFileInput, handleFileDrop, handleFileSelect,
            openTemplatePreview, closeTemplatePreview, applyTemplate, goBackToRecommend,
            getPreviewPanelStyle, getPreviewInnerStyle, getPreviewParts, getColor,
            handleWheel, startPan, resetView,
            startMove, panelRef, activeGuides,
            hasInvalid,
            undo, redo, canUndo, canRedo,
            formatValue, getScoreBadgeClass,
            // 多面板只读
            multiPanels, isMultiPanelMode, multiPanelTotalSize, getPanelOffset
        };
    }
};

createApp(App).mount('#app');
