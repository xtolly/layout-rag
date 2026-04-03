/**
 * 智能选配系统 — 前端逻辑 v2
 *
 * 新增：
 *   - 箱柜添加/编辑弹窗 (cabinetModal)
 *   - 右侧 AI 聊天界面（SSE 流式 + 工具动作实时渲染）
 *   - API Key 运行时配置
 */
const { createApp, ref, reactive, computed, nextTick } = Vue;

// ── 工具 ──────────────────────────────────────────────────────
const uid = () => crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
const API = `${window.location.origin}/api`;
const SELECTION_CONFIG_URL = '/static/configurator_options.json';

const EMPTY_SELECTION_CONFIG = Object.freeze({
    cabinet_use_options: [],
    cabinet_model_options: [],
    panel_type_options: [],
    wiring_method_options: [],
    operation_method_options: [],
    part_type_options: [],
});

const normalizeOptionList = (values) => {
    if (!Array.isArray(values)) return [];
    return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))];
};

// ── 工厂 ──────────────────────────────────────────────────────
let _orderCounter = 1000;
const getOrder = () => Date.now() + (_orderCounter++);

// ══════════════════════════════════════════════════════════════
const App = {
  setup() {

    const CABINET_USE_OPTIONS = ref([...EMPTY_SELECTION_CONFIG.cabinet_use_options]);
    const CABINET_MODEL_OPTIONS = ref([...EMPTY_SELECTION_CONFIG.cabinet_model_options]);
    const PANEL_TYPE_OPTIONS = ref([...EMPTY_SELECTION_CONFIG.panel_type_options]);
    const WIRING_METHOD_OPTIONS = ref([...EMPTY_SELECTION_CONFIG.wiring_method_options]);
    const OPERATION_METHOD_OPTIONS = ref([...EMPTY_SELECTION_CONFIG.operation_method_options]);
    const PART_TYPE_OPTIONS = ref([...EMPTY_SELECTION_CONFIG.part_type_options]);

    const applySelectionConfig = (config = EMPTY_SELECTION_CONFIG) => {
        CABINET_USE_OPTIONS.value = normalizeOptionList(config.cabinet_use_options);
        CABINET_MODEL_OPTIONS.value = normalizeOptionList(config.cabinet_model_options);
        PANEL_TYPE_OPTIONS.value = normalizeOptionList(config.panel_type_options);
        WIRING_METHOD_OPTIONS.value = normalizeOptionList(config.wiring_method_options);
        OPERATION_METHOD_OPTIONS.value = normalizeOptionList(config.operation_method_options);
        PART_TYPE_OPTIONS.value = normalizeOptionList(config.part_type_options);
    };

    const loadSelectionConfig = async () => {
        try {
            const response = await fetch(SELECTION_CONFIG_URL, { cache: 'no-store' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            applySelectionConfig(await response.json());
        } catch (error) {
            console.warn('selection config load failed', error);
        }
    };

    const getFirstOption = (optionsRef, fallback = '') => optionsRef.value[0] || fallback;
    const makePart = (o={}) => ({ part_id:uid(), order:getOrder(), part_type:'', part_model:'', part_number:1, part_width:60, part_height:80, ...o });
    const makePanel = (o={}) => ({ panel_id:uid(), order:getOrder(), panel_type:getFirstOption(PANEL_TYPE_OPTIONS), operation_method:'', panel_width:600, panel_height:1400, parts:[], is_laid_out:false, arrange:{}, ...o });
    const makeCabinet = (o={}) => ({ cabinet_id:uid(), order:getOrder(), cabinet_name:'', cabinet_use:getFirstOption(CABINET_USE_OPTIONS), cabinet_model:getFirstOption(CABINET_MODEL_OPTIONS), wiring_method:'', cabinet_width:800, cabinet_height:2200, panels:[], ...o });

    // ── 数据 ──────────────────────────────────────────────────
    const scheme = reactive({ cabinets: [] });
    const selectedCabinetId = ref(null);
    const selectedPanelId   = ref(null);
    const isLoading   = ref(false);
    const loadingText = ref('');
    const toast = reactive({ show:false, msg:'', type:'success' });
    const agentStatus = reactive({ ready:false, model:'', base_url:'', has_api_key:false });

    const loadAgentStatus = async () => {
        try {
            const response = await fetch(`${API}/agent/status`, { cache: 'no-store' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            agentStatus.ready = !!data.ready;
            agentStatus.model = String(data.model || '').trim();
            agentStatus.base_url = String(data.base_url || '').trim();
            agentStatus.has_api_key = !!data.has_api_key;
        } catch (error) {
            console.warn('agent status load failed', error);
        }
    };

    loadSelectionConfig();
    loadAgentStatus();

    // ── 从 sessionStorage 恢复备份数据 ───────────────────────────
    const _backup = sessionStorage.getItem('configurator_scheme_backup');
    if (_backup) {
        try {
            const { scheme: saved, selectedCabinetId: savedCabId, selectedPanelId: savedPanelId } = JSON.parse(_backup);
            if (saved?.cabinets?.length) {
                scheme.cabinets = saved.cabinets;
                // 延迟设置选中等待 Vue 响应式就绪
                setTimeout(() => {
                    if (savedCabId && scheme.cabinets.find(c => c.cabinet_id === savedCabId)) {
                        selectedCabinetId.value = savedCabId;
                    }
                    if (savedPanelId) {
                        const cab = scheme.cabinets.find(c => c.cabinet_id === savedCabId);
                        if (cab?.panels.find(p => p.panel_id === savedPanelId)) {
                            selectedPanelId.value = savedPanelId;
                        }
                    }
                }, 0);
            }
        } catch(e) { console.warn('scheme backup restore failed', e); }
        sessionStorage.removeItem('configurator_scheme_backup');
    }

    const layoutPanelResult = sessionStorage.getItem('layoutPanelResult');
    if (layoutPanelResult) {
        try {
            const data = JSON.parse(layoutPanelResult);
            if (data && data.scheme && data.scheme.panel_id) {
                const targetPanelId = data.scheme.panel_id;
                let foundPanel = null;
                for (const cab of scheme.cabinets) {
                    const p = cab.panels.find(x => x.panel_id === targetPanelId);
                    if (p) {
                         p.is_laid_out = true;
                         p.arrange = data.arrange;
                         foundPanel = p;
                         break;
                    }
                }
            }
        } catch(e) {
             console.warn('layoutPanelResult parse error', e);
        }
        sessionStorage.removeItem('layoutPanelResult');
    }

    // ════════════════════════════════════════════════════════
    //  布局排版工作台 iframe 管理
    // ════════════════════════════════════════════════════════
    const iframeOverlayShow     = ref(false);
    const iframeSrc             = ref('');
    const layoutIframe          = ref(null);
    const iframePanelInfo       = ref(null); // { panel_type, panel_size, parts_count }
    let _iframeMessageHandler = null;
    let _pendingIframeInit    = null; // { mode, data }

    const applyLayoutPanelResult = (data) => {
        if (!data?.scheme?.panel_id) return;
        const targetPanelId = data.scheme.panel_id;
        for (const cab of scheme.cabinets) {
            const p = cab.panels.find(x => x.panel_id === targetPanelId);
            if (p) {
                p.is_laid_out = true;
                p.arrange = data.arrange;
                showToast('面板布局已更新 ✓');
                break;
            }
        }
    };

    const closeLayoutWorkbench = () => {
        iframeOverlayShow.value = false;
        iframeSrc.value = '';
        iframePanelInfo.value = null;
        if (_iframeMessageHandler) {
            window.removeEventListener('message', _iframeMessageHandler);
            _iframeMessageHandler = null;
        }
        _pendingIframeInit = null;
    };

    const openLayoutWorkbench = (mode, data) => {
        // 清理上一次
        if (_iframeMessageHandler) {
            window.removeEventListener('message', _iframeMessageHandler);
            _iframeMessageHandler = null;
        }
        _pendingIframeInit = mode ? { mode, data } : null;
        // 设置面板信息（用于顶部标题栏）
        if (mode === 'layoutPanel' && data?.scheme) {
            iframePanelInfo.value = {
                layout_mode: data.layout_mode || '智能布局',
                panel_type:  data.scheme.panel_type  || '安装板',
                panel_size:  data.scheme.panel_size  || [600, 1400],
                parts_count: data.scheme.parts?.length || 0,
            };
        } else {
            iframePanelInfo.value = {
                layout_mode: '手动布局',
                panel_type:  null,
                panel_size:  null,
                parts_count: null,
            };
        }

        const handleMessage = (e) => {
            if (e.origin !== window.location.origin) return;
            const { type, payload, filename } = e.data || {};
            if (type === 'workbench:ready') {
                // iframe 就绪，发送初始化数据
                if (_pendingIframeInit && layoutIframe.value) {
                    layoutIframe.value.contentWindow.postMessage(
                        { type: `init:${_pendingIframeInit.mode}`, payload: _pendingIframeInit.data },
                        window.location.origin
                    );
                }
            } else if (type === 'workbench:layoutPanelResult') {
                applyLayoutPanelResult(payload);
                closeLayoutWorkbench();
            } else if (type === 'workbench:close') {
                closeLayoutWorkbench();
            }
        };
        _iframeMessageHandler = handleMessage;
        window.addEventListener('message', handleMessage);

        iframeSrc.value = '/layout';
        iframeOverlayShow.value = true;
    };

    // ── 拖拽调整列宽 ─────────────────────────────────────────
    const cabinetWidth = ref(268);
    const panelWidth   = ref(272);
    const chatWidth    = ref(360);
    const chatCollapsed = ref(false);

    const startResize = (evt, target) => {
        evt.preventDefault();
        const startX = evt.clientX;
        const startW = target === 'cabinet' ? cabinetWidth.value
                     : target === 'panel' ? panelWidth.value
                     : chatWidth.value;

        const onMove = (e) => {
            const delta = target === 'chat' ? startX - e.clientX : e.clientX - startX;
            const newW = Math.max(180, Math.min(600, startW + delta));
            if (target === 'cabinet') cabinetWidth.value = newW;
            else if (target === 'panel') panelWidth.value = newW;
            else chatWidth.value = newW;
        };
        const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); document.body.style.cursor=''; document.body.style.userSelect=''; };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    };

    const toggleChat = () => { chatCollapsed.value = !chatCollapsed.value; };

    // ── 弹窗状态 ──────────────────────────────────────────────
    const cabinetModal = reactive({ show:false, isNew:true, cabinet: makeCabinet() });
    const panelModal   = reactive({ show:false, cabinetId:null, isNew:true, panel: makePanel() });
    const partModal    = reactive({ show:false, cabinetId:null, panelId:null, isNew:true, part: makePart() });
    const jsonModal    = reactive({ show:false, raw:'' });

    // ── 计算属性 ──────────────────────────────────────────────
    const selectedCabinet = computed(() => scheme.cabinets.find(c=>c.cabinet_id===selectedCabinetId.value)||null);
    const selectedPanel   = computed(() => selectedCabinet.value?.panels.find(p=>p.panel_id===selectedPanelId.value)||null);
    const totalCabinets   = computed(() => scheme.cabinets.length);
    const totalPanels     = computed(() => scheme.cabinets.reduce((s,c)=>s+c.panels.length, 0));
    const totalParts      = computed(() => scheme.cabinets.reduce((s,c)=>s+c.panels.reduce((sp,p)=>sp+p.parts.reduce((sq,pt)=>sq+(pt.part_number||1),0),0), 0));

    const sortedCabinets = computed(() => [...scheme.cabinets].sort((a,b)=>(a.order||0)-(b.order||0)));
    const sortedPanels   = computed(() => selectedCabinet.value ? [...selectedCabinet.value.panels].sort((a,b)=>(a.order||0)-(b.order||0)) : []);
    const sortedParts    = computed(() => selectedPanel.value ? [...selectedPanel.value.parts].sort((a,b)=>(a.order||0)-(b.order||0)) : []);

    // ── Toast ──────────────────────────────────────────────────
    let _toastTimer = null;
    const showToast = (msg, type='success') => {
        toast.msg=msg; toast.type=type; toast.show=true;
        clearTimeout(_toastTimer);
        _toastTimer = setTimeout(()=>toast.show=false, 2800);
    };

    // ══════════════════════════════════════════════════════════
    //  箱柜操作
    // ══════════════════════════════════════════════════════════
    const openAddCabinet = () => {
        cabinetModal.cabinet = makeCabinet({ cabinet_name:`柜${scheme.cabinets.length+1}` });
        cabinetModal.isNew   = true;
        cabinetModal.show    = true;
    };
    const openEditCabinet = (cab) => {
        cabinetModal.cabinet = JSON.parse(JSON.stringify(cab));
        cabinetModal.isNew   = false;
        cabinetModal.show    = true;
    };
    const saveCabinetModal = () => {
        if (!cabinetModal.cabinet.cabinet_name.trim()) return showToast('请填写柜编号','warn');
        if (cabinetModal.isNew) {
            scheme.cabinets.push({ ...cabinetModal.cabinet, panels: cabinetModal.cabinet.panels||[] });
            selectCabinet(cabinetModal.cabinet.cabinet_id);
            showToast('已添加箱柜');
        } else {
            const idx = scheme.cabinets.findIndex(c=>c.cabinet_id===cabinetModal.cabinet.cabinet_id);
            if (idx!==-1) {
                const panels = scheme.cabinets[idx].panels; // 保留原 panels
                Object.assign(scheme.cabinets[idx], { ...cabinetModal.cabinet, panels });
            }
            showToast('已保存箱柜');
        }
        cabinetModal.show = false;
    };
    const removeCabinet = (id) => {
        if (!confirm('确定删除此箱柜及其所有面板和元件？')) return;
        const idx = scheme.cabinets.findIndex(c=>c.cabinet_id===id);
        if (idx!==-1) scheme.cabinets.splice(idx,1);
        if (selectedCabinetId.value===id) { selectedCabinetId.value=null; selectedPanelId.value=null; }
        showToast('已删除','warn');
    };
    const duplicateCabinet = (cab) => {
        const copy = JSON.parse(JSON.stringify(cab));
        copy.cabinet_id = uid(); copy.cabinet_name += '_副本';
        copy.panels.forEach(p=>{ p.panel_id=uid(); p.parts.forEach(pt=>pt.part_id=uid()); });
        const idx = scheme.cabinets.findIndex(c=>c.cabinet_id===cab.cabinet_id);
        scheme.cabinets.splice(idx+1,0,copy);
        showToast('已复制箱柜');
    };
    const selectCabinet = (id) => { 
        selectedCabinetId.value = id; 
        const cab = scheme.cabinets.find(c => c.cabinet_id === id);
        if (cab && cab.panels.length > 0) {
            selectedPanelId.value = cab.panels[0].panel_id;
        } else {
            selectedPanelId.value = null;
        }
    };

    // ══════════════════════════════════════════════════════════
    //  面板操作
    // ══════════════════════════════════════════════════════════
    const openAddPanel = (cabinetId) => {
        panelModal.cabinetId=cabinetId; panelModal.panel=makePanel(); panelModal.isNew=true; panelModal.show=true;
    };
    const openEditPanel = (cabinetId, panel) => {
        panelModal.cabinetId=cabinetId; panelModal.panel=JSON.parse(JSON.stringify(panel)); panelModal.isNew=false; panelModal.show=true;
    };
    const savePanelModal = () => {
        const cab = scheme.cabinets.find(c=>c.cabinet_id===panelModal.cabinetId);
        if (!cab) return;
        if (panelModal.isNew) {
            cab.panels.push(panelModal.panel);
            selectedPanelId.value = panelModal.panel.panel_id;
            showToast('已添加面板');
        } else {
            const idx = cab.panels.findIndex(p=>p.panel_id===panelModal.panel.panel_id);
            if (idx!==-1) Object.assign(cab.panels[idx], panelModal.panel); showToast('已保存面板');
        }
        panelModal.show=false;
    };
    const removePanel = (cabinetId, panelId) => {
        if (!confirm('确定删除此面板及其所有元件？')) return;
        const cab = scheme.cabinets.find(c=>c.cabinet_id===cabinetId);
        if (!cab) return;
        const idx = cab.panels.findIndex(p=>p.panel_id===panelId);
        if (idx!==-1) cab.panels.splice(idx,1);
        if (selectedPanelId.value===panelId) selectedPanelId.value=null;
        showToast('已删除','warn');
    };
    const selectPanel = (id) => { selectedPanelId.value=id; };

    // ══════════════════════════════════════════════════════════
    //  元件操作
    // ══════════════════════════════════════════════════════════
    const openAddPart = (cabinetId, panelId) => {
        partModal.cabinetId=cabinetId; partModal.panelId=panelId; partModal.part=makePart(); partModal.isNew=true; partModal.show=true;
    };
    const openEditPart = (cabinetId, panelId, part) => {
        partModal.cabinetId=cabinetId; partModal.panelId=panelId; partModal.part=JSON.parse(JSON.stringify(part)); partModal.isNew=false; partModal.show=true;
    };
    const savePartModal = () => {
        const cab = scheme.cabinets.find(c=>c.cabinet_id===partModal.cabinetId);
        const panel = cab?.panels.find(p=>p.panel_id===partModal.panelId);
        if (!panel) return;
        if (partModal.isNew) { panel.parts.push(partModal.part); showToast('已添加元件'); }
        else { const idx=panel.parts.findIndex(p=>p.part_id===partModal.part.part_id); if (idx!==-1) Object.assign(panel.parts[idx],partModal.part); showToast('已保存'); }
        partModal.show=false;
    };
    const removePart = (cabinetId, panelId, partId) => {
        const panel = scheme.cabinets.find(c=>c.cabinet_id===cabinetId)?.panels.find(p=>p.panel_id===panelId);
        if (!panel) return;
        const idx=panel.parts.findIndex(p=>p.part_id===partId);
        if (idx!==-1) panel.parts.splice(idx,1);
        showToast('已删除','warn');
    };

    // ══════════════════════════════════════════════════════════
    //  导入 / 导出
    // ══════════════════════════════════════════════════════════
    const jsonFileInput = ref(null);
    const triggerJsonFileInput = () => jsonFileInput.value?.click();
    const handleJsonFile = (e) => {
        const file = e.target.files[0]; if (!file) return;
        const r = new FileReader();
        r.onload = (ev) => { jsonModal.raw=ev.target.result; jsonModal.show=true; };
        r.readAsText(file); e.target.value='';
    };
    const openJsonModal = () => {
        jsonModal.raw = JSON.stringify({ cabinets: scheme.cabinets }, null, 2);
        jsonModal.show=true;
    };
    const importJsonFromText = () => {
        try {
            const parsed = JSON.parse(jsonModal.raw);
            if (!parsed.cabinets) throw new Error('缺少 cabinets 字段');
            scheme.cabinets = parsed.cabinets;
            jsonModal.show=false; showToast(`已导入 ${scheme.cabinets.length} 个箱柜`);
        } catch(e) { showToast('JSON 格式错误: '+e.message,'error'); }
    };
    const exportJson = () => {
        const blob = new Blob([JSON.stringify({cabinets:scheme.cabinets},null,2)], {type:'application/json'});
        const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
        a.download=`scheme_${Date.now()}.json`; a.click(); showToast('已导出');
    };

    const exportPanelData = () => {
        if (!selectedPanel.value) return showToast('请先选择一个面板', 'warn');
        const panel = selectedPanel.value;
        const cabinet = selectedCabinet.value;
        
        const generateUUID = () => {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        };

        const newUuid = generateUUID();
        const cabinetUse = cabinet?.cabinet_use || '';
        const cabinetModel = cabinet?.cabinet_model || '';
        const panelType = panel.panel_type || '';
        const pWidth = panel.panel_width || 0;
        const pHeight = panel.panel_height || 0;
        
        const name = `${cabinetUse}-${cabinetModel}-${panelType}-${pWidth}x${pHeight}`;
        
        const partsFlat = [];
        panel.parts.forEach(part => {
            const qty = part.part_number || 1;
            for (let i = 0; i < qty; i++) {
                partsFlat.push({
                    parent_id: part.part_id,
                    part_id: generateUUID(),
                    part_type: part.part_type || '',
                    part_model: part.part_model || '',
                    part_size: [part.part_width || 0, part.part_height || 0]
                });
            }
        });

        const exportData = {
            name: name,
            uuid: newUuid,
            scheme: {
                cabinet_name: cabinet?.cabinet_name || '',
                cabinet_use: cabinetUse,
                cabinet_model: cabinetModel,
                panel_id: panel.panel_id,
                panel_type: panelType,
                panel_size: [pWidth, pHeight],
                parts: partsFlat
            }
        };

        const blob = new Blob([JSON.stringify(exportData, null, 2)], {type:'application/json'});
        const a = document.createElement('a'); 
        a.href = URL.createObjectURL(blob);
        a.download = `panel_${name}_${Date.now()}.json`;
        a.click();
        showToast('已导出面板');
    };

    const sendToLayout = () => {
        openLayoutWorkbench(null, null);
    };

    const sendWorkbenchBack = () => {
        if (layoutIframe.value?.contentWindow)
            layoutIframe.value.contentWindow.postMessage({ type: 'workbench:requestBack' }, window.location.origin);
    };

    const sendWorkbenchSubmit = () => {
        if (layoutIframe.value?.contentWindow)
            layoutIframe.value.contentWindow.postMessage({ type: 'workbench:requestSubmit' }, window.location.origin);
    };

    // ══════════════════════════════════════════════════════════
    //  AI 聊天
    // ══════════════════════════════════════════════════════════
    const chatMessages   = ref([]);
    const chatInput      = ref('');
    const chatLoading    = ref(false);
    const chatImageFile  = ref(null);
    const chatImagePreview = ref(null);
    const chatScrollEl   = ref(null);
    const chatTextarea   = ref(null);
    const chatImageInput = ref(null);
    const createChatSessionId = () => {
        if (window.crypto?.randomUUID) return window.crypto.randomUUID();
        return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    };
    const chatSessionId = ref(sessionStorage.getItem('configurator_chat_session_id') || createChatSessionId());
    sessionStorage.setItem('configurator_chat_session_id', chatSessionId.value);
    const quickHints = [
        '🔌 生成一套标准低压配电方案，含进线柜和2台出线柜',
        '⚡ 250A 电动机控制回路，含断路器、接触器和热继电器',
        '📋 帮我分析当前方案并给出优化建议',
    ];

    // 清空会话
    const clearChatSession = () => {
        chatMessages.value = [];
        chatInput.value = '';
        chatSessionId.value = createChatSessionId();
        sessionStorage.setItem('configurator_chat_session_id', chatSessionId.value);
        clearChatImage();
        showToast('已开启新会话');
    };

    const scrollChat = () => nextTick(()=>{ if (chatScrollEl.value) chatScrollEl.value.scrollTop=chatScrollEl.value.scrollHeight; });

    // 自动调整输入框高度
    const autoResize = () => {
        const el = chatTextarea.value; if (!el) return;
        el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,120)+'px';
    };

    const triggerChatImage = () => chatImageInput.value?.click();
    const handleChatImage = (e) => {
        const file=e.target.files[0]; if (!file) return;
        chatImageFile.value=file;
        const r=new FileReader(); r.onload=ev=>chatImagePreview.value=ev.target.result; r.readAsDataURL(file);
        e.target.value='';
    };
    const clearChatImage = () => { chatImageFile.value=null; chatImagePreview.value=null; };

    // Ctrl+V 粘贴剪贴板图片
    const handlePaste = (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                if (!file) return;
                chatImageFile.value = file;
                const r = new FileReader();
                r.onload = ev => chatImagePreview.value = ev.target.result;
                r.readAsDataURL(file);
                return;
            }
        }
    };

    const sendQuickHint = (hint) => { chatInput.value=hint; sendChat(); };

    // 将 AI 工具动作应用到方案
    const applyAction = (action) => {
        if (!action || !action.action) return;
        const { action: type } = action;

        if (type === 'replace_scheme' && action.scheme?.cabinets) {
            scheme.cabinets = action.scheme.cabinets;
            showToast(`AI 已生成 ${scheme.cabinets.length} 个箱柜方案`);
        }
        else if (type === 'add_cabinets' && action.cabinets?.length) {
            action.cabinets.forEach(cab => {
                scheme.cabinets.push({ ...cab, panels: cab.panels||[] });
            });
            showToast(`已批量添加 ${action.cabinets.length} 个箱柜`);
        }
        else if (type === 'add_panels' && action.panels?.length) {
            const cab = scheme.cabinets.find(c=>c.cabinet_id===action.cabinet_id);
            if (cab) { 
                action.panels.forEach(p => cab.panels.push(p));
                showToast(`已批量添加 ${action.panels.length} 个面板`);
            }
        }
        else if (type === 'add_parts' && action.parts?.length) {
            let foundPanel = null;
            for (const cab of scheme.cabinets) {
                const panel = cab.panels.find(p=>p.panel_id===action.panel_id);
                if (panel) { foundPanel = panel; break; }
            }
            if (foundPanel) { 
                action.parts.forEach(pt => foundPanel.parts.push(pt));
                showToast(`已批量添加 ${action.parts.length} 个元件`);
            }
        }
        else if (type === 'edit_cabinet' && action.updates) {
            const cab = scheme.cabinets.find(c=>c.cabinet_id===action.cabinet_id);
            if (cab) { Object.assign(cab, action.updates); showToast('已修改箱柜'); }
        }
        else if (type === 'edit_panel' && action.updates) {
            for (const cab of scheme.cabinets) {
                const panel = cab.panels.find(p=>p.panel_id===action.panel_id);
                if (panel) { Object.assign(panel, action.updates); showToast('已修改面板'); break; }
            }
        }
        else if (type === 'edit_part' && action.updates) {
            for (const cab of scheme.cabinets) {
                for (const panel of cab.panels) {
                    const part = panel.parts.find(pt=>pt.part_id===action.part_id);
                    if (part) { Object.assign(part, action.updates); showToast('已修改元件'); return; }
                }
            }
        }
    };

    // 发送消息（SSE 流式）
    const sendChat = async () => {
        const text = chatInput.value.trim();
        if ((!text && !chatImagePreview.value) || chatLoading.value) return;

        // 用户消息（保存图片预览供显示）
        const msgImage = chatImagePreview.value || null;
        chatMessages.value.push({ role:'user', content: text, image: msgImage });
        chatInput.value=''; if (chatTextarea.value) chatTextarea.value.style.height='auto';
        chatLoading.value=true; scrollChat();

        const currentScheme = { cabinets: JSON.parse(JSON.stringify(scheme.cabinets)) };
        const imageData = chatImagePreview.value || null;
        const payload = {
            session_id: chatSessionId.value,
            message: text || '请根据图片生成配置方案',
            scheme: currentScheme,
            image: imageData,
            selection: {
                cabinet_id: selectedCabinetId.value || '',
                panel_id: selectedPanelId.value || '',
            },
        };

        // AI 回复消息占位
        const aiMsgIdx = chatMessages.value.length;
        chatMessages.value.push({ role:'ai', content:'' });
        clearChatImage();

        try {
            const response = await fetch(`${API}/agent/chat/stream`, {
                method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify(payload)
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const reader  = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream:true });

                const lines = buffer.split('\n\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const evt = JSON.parse(line.slice(6));

                        if (evt.type === 'token') {
                            let aiMsg = chatMessages.value[aiMsgIdx];
                            aiMsg.rawContent = (aiMsg.rawContent || '') + evt.content;
                            
                            let raw = aiMsg.rawContent;
                            let start = raw.indexOf('<think>');
                            let end = raw.indexOf('</think>');
                            
                            if (start !== -1) {
                                if (end !== -1) {
                                    aiMsg.thinking = raw.substring(start + 7, end).replace(/^\n+|\n+$/g, '');
                                    aiMsg.content = raw.substring(0, start) + raw.substring(end + 8);
                                } else {
                                    aiMsg.thinking = raw.substring(start + 7).replace(/^\n+/, '');
                                    aiMsg.content = raw.substring(0, start);
                                }
                            } else {
                                aiMsg.content = raw;
                            }
                            scrollChat();
                        }
                        else if (evt.type === 'thinking') {
                            // 追加思考过程
                            if (!chatMessages.value[aiMsgIdx].thinking) {
                                chatMessages.value[aiMsgIdx].thinking = '';
                            }
                            chatMessages.value[aiMsgIdx].thinking += evt.content;
                            scrollChat();
                        }
                        else if (evt.type === 'action') {
                            // 工具动作：添加卡片 + 应用到方案
                            applyAction(evt.action);
                            chatMessages.value.push({ role:'action', content: evt.action?.message || '已执行操作' });
                            scrollChat();
                        }
                        else if (evt.type === 'done') {
                            chatLoading.value = false;
                            // 如果 AI 没有文字回复但有动作，给一个友好提示
                            if (!chatMessages.value[aiMsgIdx].content && evt.actions?.length) {
                                chatMessages.value[aiMsgIdx].content = '方案已自动填充到左侧，请查看并按需调整。';
                            }
                        }
                        else if (evt.type === 'error') {
                            chatMessages.value[aiMsgIdx].content = `❌ ${evt.message}`;
                            chatLoading.value = false;
                        }
                    } catch(e) { /* 忽略单条解析错误 */ }
                }
            }
        } catch(e) {
            chatMessages.value[aiMsgIdx].content = `❌ 请求失败：${e.message}\n\n请检查 API Key 配置或后端是否运行。`;
        } finally {
            chatLoading.value = false;
            scrollChat();
        }
    };

    // ══════════════════════════════════════════════════════════
    //  工具函数
    // ══════════════════════════════════════════════════════════
    const getPanelPartCount = (panel) => panel.parts.reduce((s,p)=>s+(p.part_number||1),0);

    const isPanelValidForLayout = computed(() => {
        const pnl = selectedPanel.value;
        if (!pnl) return false;
        if (!parseFloat(pnl.panel_width) || !parseFloat(pnl.panel_height)) return false;
        
        let partsCount = 0;
        let allValid = true;
        pnl.parts.forEach(part => {
            if (!parseFloat(part.part_width) || !parseFloat(part.part_height)) allValid = false;
            partsCount += parseInt(part.part_number) || 1;
        });
        
        if (!allValid) return false;
        return partsCount > 1;
    });

    const layoutPanel = () => {
        if (!isPanelValidForLayout.value) return;
        const cab = selectedCabinet.value;
        const pnl = selectedPanel.value;
        
        const generateUuid = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });

        const expandedParts = [];
        pnl.parts.forEach(part => {
            let count = parseInt(part.part_number) || 1;
            for (let i = 0; i < count; i++) {
                expandedParts.push({
                    parent_id: part.part_id,
                    part_id: generateUuid(),
                    part_type: part.part_type,
                    part_model: part.part_model,
                    part_size: [parseFloat(part.part_width)||80, parseFloat(part.part_height)||100]
                });
            }
        });

        const templateData = {
            name: `${cab.cabinet_use}-${cab.cabinet_model||''}-${pnl.panel_type}-${pnl.panel_width}x${pnl.panel_height}`,
            uuid: generateUuid(),
            layout_mode: pnl.is_laid_out ? '查看布局' : '智能布局',
            scheme: {
                cabinet_name: cab.cabinet_name || '',
                cabinet_use: cab.cabinet_use || '',
                cabinet_model: cab.cabinet_model || '',
                cabinet_wiring_method: cab.wiring_method || '',
                panel_id: pnl.panel_id,
                panel_type: pnl.panel_type || '',
                panel_operation_method: pnl.operation_method || '',
                panel_size: [parseFloat(pnl.panel_width)||600, parseFloat(pnl.panel_height)||1400],
                parts: expandedParts
            }
        };

        // 展开到布局排版工作台
        openLayoutWorkbench('layoutPanel', templateData);
    };

    const getCabinetStats   = (cab) => ({
        panels: cab.panels.length,
        parts:  cab.panels.reduce((s,p)=>s+getPanelPartCount(p),0),
    });
    // Markdown 渲染
    const renderMd = (text) => {
        if (!text) return '';
        if (typeof marked !== 'undefined') {
            marked.setOptions({ breaks: true, gfm: true });
            const html = typeof marked.parse === 'function' ? marked.parse(text) : marked(text);
            if (typeof DOMPurify !== 'undefined') return DOMPurify.sanitize(html);
            return html;
        }
        // fallback：转义并保留换行
        return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    };

    return {
        scheme, selectedCabinetId, selectedPanelId,
        selectedCabinet, selectedPanel,
        sortedCabinets, sortedPanels, sortedParts,
        isLoading, loadingText, toast,
        agentStatus,
        cabinetModal, panelModal, partModal, jsonModal,
        jsonFileInput, chatImageInput,
        totalCabinets, totalPanels, totalParts,
        CABINET_USE_OPTIONS, CABINET_MODEL_OPTIONS, PANEL_TYPE_OPTIONS, PART_TYPE_OPTIONS,
        WIRING_METHOD_OPTIONS, OPERATION_METHOD_OPTIONS,
        // 拖拽 & 折叠
        cabinetWidth, panelWidth, chatWidth, chatCollapsed, startResize, toggleChat,
        // 箱柜
        openAddCabinet, openEditCabinet, saveCabinetModal, removeCabinet, duplicateCabinet, selectCabinet,
        // 面板
        openAddPanel, openEditPanel, savePanelModal, removePanel, selectPanel,
        // 元件
        openAddPart, openEditPart, savePartModal, removePart,
        // JSON
        exportJson, exportPanelData, openJsonModal, importJsonFromText, triggerJsonFileInput, handleJsonFile, sendToLayout, sendWorkbenchBack, sendWorkbenchSubmit, layoutPanel, isPanelValidForLayout,
        iframeOverlayShow, iframeSrc, layoutIframe, closeLayoutWorkbench,
        iframePanelInfo,
        // 聊天
        chatMessages, chatInput, chatLoading, chatScrollEl, chatTextarea, chatImageInput,
        chatImagePreview, quickHints,
        triggerChatImage, handleChatImage, clearChatImage, handlePaste, sendChat, sendQuickHint,
        clearChatSession, autoResize, renderMd,
        // 工具
        getPanelPartCount, getCabinetStats,
    };
  }
};

createApp(App).mount('#app');
