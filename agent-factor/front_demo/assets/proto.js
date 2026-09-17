const ROLES = {admin:'项目管理员', developer:'开发成员', viewer:'只读访客'};
const CUR_USER = '张伟';
const AGENTS = [
  {id:'shennong-crash', dir:'shennong-crash-agent', prefix:'shennong-crash-agent/', en:true, pkg:'witty-agent-shennong', name:'神农宕机诊断', desc:'内核宕机日志（vmcore/dmesg）特征提取与根因定位，覆盖 panic/oops/lockup 等场景。', long:'面向 Linux/openEuler 内核宕机场景的诊断 Agent：从 vmcore-dmesg / kern 日志提取崩溃特征（RIP、CallTrace、关联模块），经指纹匹配与 RAG 检索定位已知问题，并结合 vmcore 双轨逆向分析产出根因结论与修复建议。', ver:'0.10.5', last:'f', dl:132, style:'plain', sizeOn:'4.2MB', sizeOff:'386MB', skills:[['vmcore-analysis','vmcore 双轨逆向分析（寄存器/内存布局还原）'],['dmesg-feature-extract','宕机特征提取与指纹匹配（RIP/CallTrace/模块）'],['crash-report-gen','按统一 JSON Schema 生成诊断报告']], tint:'#fef2f2', tc:'#ef4444'},
  {id:'nl2sql', dir:'NL2sql-Agent', prefix:'NL2sql-Agent/', en:true, pkg:'witty-agent-nl2sql', name:'NL2SQL 查询助手', desc:'自然语言转只读查询并执行（ES IR / OpenGauss SQL / HBase scan）。', long:'将自然语言问题转换为受控只读查询并在 ES IR / OpenGauss / HBase 上执行：支持澄清追问、规则导入与冷启动、问答一致性校验，全程走 CLI 只读引擎，杜绝写操作。', ver:'0.8.2', last:'s', dl:87, style:'plain', sizeOn:'2.9MB', sizeOff:'96MB', skills:[['nl-query','自然语言 → 只读查询（SQL/DSL/scan）'],['readonly-exec','多引擎只读执行与结果裁剪'],['rule-import','领域规则导入与冷启动']], tint:'#ebf2ff', tc:'#1e6fff'},
  {id:'openeuler-ops', dir:'openeuler-ops-agent', prefix:'openeuler-ops-agent/', en:true, pkg:'@openeuler/witty-agent-openeuler-ops', name:'openEuler 运维助手', desc:'故障排查 / 巡检 / CVE / 加固 / 调优等 16 个运维场景。', long:'覆盖 openEuler 生产运维 16 个高频场景：故障排查、日常巡检、CVE 跟踪、安全加固、内核参数调优等。内置场景化工作流与知识检索，输出可执行命令清单与风险提示。', ver:'1.2.0', last:'s', dl:210, style:'organization', sizeOn:'5.1MB', sizeOff:'386MB', skills:[['fault-triage','故障场景化排查向导'],['cve-scan','CVE 比对与影响面评估'],['hardening','基线加固检查单生成'],['sys-tuning','内核参数调优建议']], tint:'#f5f3ff', tc:'#7c3aed'},
  {id:'xlite-perf-optimizer', dir:'xlite-perf-optimizer-agent', prefix:'xlite-perf-optimizer-agent/', en:false, pkg:'@openeuler/witty-agent-xlite', name:'轻量性能优化器', desc:'面向轻量级内核的性能调优建议与验证。当前已禁用构建，不参与增量构建计划。', long:'面向轻量级内核（内存受限/裁剪场景）的性能剖析与调优建议：采集轻量指标、生成优化清单并支持 A/B 验证。当前处于停演进状态，仅保留注册信息。', ver:'0.4.1', last:'c', dl:0, style:'organization', sizeOn:'3.0MB', sizeOff:'128MB', skills:[['lite-perf-profile','轻量级性能剖析（低开销采样）']], tint:'#fff7ed', tc:'#f59e0b'},
  {id:'log-detection', dir:'log-detection-agent', prefix:'log-detection-agent/', en:true, name:'日志异常检测', desc:'关键词 / 聚类 / LLM / embedding 多模式日志异常检测（mock 演示数据）。', long:'对文本日志做多模式异常检测：关键词规则、聚类离群点、LLM 智能判定与 embedding 相似度精排，输出异常原因与评分。', ver:'0.6.3', last:'s', dl:45, style:'plain', sizeOn:'3.4MB', sizeOff:'142MB', skills:[['keyword-detect','关键词规则异常检测'],['cluster-detect','聚类离群点检测'],['embedding-rank','embedding+关键字精排']], tint:'#ebf2ff', tc:'#1e6fff'},
  {id:'crash-report', dir:'crash-report-agent', prefix:'crash-report-agent/', en:true, name:'宕机报告生成', desc:'按统一 JSON Schema 生成内核宕机诊断报告（mock 演示数据）。', long:'汇聚基线、特征提取、案例检索与工作流追踪，产出符合统一 JSON Schema 的内核宕机诊断报告。', ver:'0.3.0', last:'s', dl:30, style:'plain', sizeOn:'2.1MB', sizeOff:'88MB', skills:[['schema-report','Schema 化报告生成'],['workflow-trace','工作流追踪与留痕']], tint:'#ecfdf5', tc:'#00b365'},
  {id:'kernel-dataset', dir:'kernel-dataset-agent', prefix:'kernel-dataset-agent/', en:true, name:'内核数据集巡检', desc:'linux / openEuler 数据集增量更新与水位回补（mock 演示数据）。', long:'维护 linux 与 openEuler 数据集（bugzilla / commit / LKML / issue）的增量采集、水位续传、空洞回补与目录巡检。', ver:'0.9.1', last:'s', dl:12, style:'organization', sizeOn:'2.6MB', sizeOff:'210MB', skills:[['dataset-sync','增量采集与水位续传'],['backfill','空洞回补与分片滚动']], tint:'#f5f3ff', tc:'#7c3aed'},
  {id:'sched-diagnosis', dir:'sched-diagnosis-agent', prefix:'sched-diagnosis-agent/', en:true, name:'调度器诊断', desc:'CFS 空指针解引用场景的方法论诊断（mock 演示数据）。', long:'针对 kernel/sched/fair.c 空指针解引用（set_next_entity / pick_next_task_fair 等）场景的识别、定界与修复建议。', ver:'0.2.4', last:'c', dl:8, style:'plain', sizeOn:'1.8MB', sizeOff:'64MB', skills:[['sched-nullptr-diag','调度器空指针场景方法论诊断']], tint:'#fff7ed', tc:'#f59e0b'},
  {id:'perf-analyzer', dir:'perf-analyzer-agent', prefix:'perf-analyzer-agent/', en:true, name:'性能分析', desc:'火焰图 / 指标采样的性能归因分析（mock 演示数据）。', long:'基于火焰图与指标采样的性能归因：热点定位、偏差检测与优化优先级排序。', ver:'0.5.7', last:'s', dl:26, style:'organization', sizeOn:'3.9MB', sizeOff:'156MB', skills:[['flame-analysis','火焰图热点归因'],['metrics-collect','低开销指标采集']], tint:'#fef2f2', tc:'#ef4444'},
  {id:'security-scan', dir:'security-scan-agent', prefix:'security-scan-agent/', en:true, name:'安全扫描', desc:'CVE 比对与依赖漏洞扫描（mock 演示数据）。', long:'对组件依赖与内核配置做 CVE 比对、漏洞扫描与修复建议（含 CVSS 评分与攻击向量分析）。', ver:'0.4.2', last:'f', dl:19, style:'plain', sizeOn:'2.4MB', sizeOff:'102MB', skills:[['cve-compare','CVE 比对与受影响产品圈定'],['dep-scan','依赖漏洞扫描']], tint:'#ebf2ff', tc:'#1e6fff'},
  {id:'compat-matrix', dir:'compat-matrix-agent', prefix:'compat-matrix-agent/', en:true, name:'兼容性矩阵', desc:'硬件 / OS 兼容性测试矩阵维护（mock 演示数据）。', long:'维护整机/板卡兼容性测试矩阵：用例执行状态、认证进度与版本覆盖关系。', ver:'0.1.9', last:'s', dl:6, style:'plain', sizeOn:'1.6MB', sizeOff:'52MB', skills:[['matrix-maintain','兼容性矩阵维护与查询']], tint:'#ecfdf5', tc:'#00b365'},
  {id:'docs-writer', dir:'docs-writer-agent', prefix:'docs-writer-agent/', en:true, name:'文档生成', desc:'基于工作流追踪自动生成技术文档（mock 演示数据）。', long:'基于任务执行留痕与代码变更自动生成/更新技术文档，保持文档与实现同步。', ver:'0.2.0', last:'s', dl:3, style:'organization', sizeOn:'1.9MB', sizeOff:'58MB', skills:[['doc-gen','文档自动生成与增量更新']], tint:'#f5f3ff', tc:'#7c3aed'}
];
const pkgName = a => a.pkg || (a.style==='organization' ? '@openeuler/witty-agent-'+a.id : 'witty-agent-'+a.id);
const PIE_COLORS = ['#1e6fff','#00b365','#7c3aed','#f59e0b'];
let agentDrawerEl = null;
function closeAgentDrawer(){ if (agentDrawerEl) agentDrawerEl.classList.remove('show'); const ov=$('#drawerOverlay'); ov && ov.classList.remove('show'); }
function copyText(txt, label){
  if (navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(txt).then(()=>toast('已复制'+(label||'')+'（mock）','s'), ()=>toast(txt)); }
  else toast('已复制'+(label||'')+'（mock）','s');
}
function openDlPicker(id, pre){
  const a = AGENTS.find(x=>x.id===id);
  if (!a) return;
  const on = pre!=='offline', off = pre==='offline';
  confirmBox('下载产物 · '+a.name,
    '<div class="dim" style="margin-bottom:10px">版本 <span class="mono">'+a.ver+'</span> · 勾选需要下载的产物类型：</div>'+
    '<label class="dl-opt"><input type="checkbox" id="dlOn" '+(on?'checked':'')+'><div><b>在线包（online tgz）</b><div class="dim mono">'+pkgName(a)+'-'+a.ver+'.tgz · '+a.sizeOn+' · npm registry · 不含 Python wheels</div></div></label>'+
    '<label class="dl-opt"><input type="checkbox" id="dlOff" '+(off?'checked':'')+'><div><b>离线包（offline tgz）</b><div class="dim mono">'+pkgName(a)+'-offline-'+a.ver+'.tgz · '+a.sizeOff+' · 构建服务器 artifacts 目录 · 含 Python wheels</div></div></label>',
    {okText:'下载所选', onOk:()=>{
      const sel = [];
      if ($('#dlOn') && $('#dlOn').checked) sel.push('在线包 '+pkgName(a)+'-'+a.ver+'.tgz（'+a.sizeOn+'）');
      if ($('#dlOff') && $('#dlOff').checked) sel.push('离线包 '+pkgName(a)+'-offline-'+a.ver+'.tgz（'+a.sizeOff+'）');
      if (!sel.length){ toast('请至少勾选一种产物类型','w'); return false; }
      toast('开始下载'+(sel.length>1?'（并行 2 个任务）':'')+'：'+sel.join('；')+'（mock，带权限校验的临时链接）','s');
    }});
}
function openAgentDrawer(id){
  const a = AGENTS.find(x=>x.id===id);
  if (!a) return;
  if (agentDrawerEl) agentDrawerEl.remove();
  agentDrawerEl = document.createElement('div'); agentDrawerEl.className = 'drawer';
  const npmCmd = 'npm install -g ' + pkgName(a) + '@' + a.ver + ' --registry=https://registry.npmjs.org/';
  const scpCmd = 'scp deploy@jenkins-node:/home/witty-agents-jenkins/artifacts/' + a.id + '/' + a.ver + '/' + pkgName(a) + '-offline-' + a.ver + '.tgz .';
  agentDrawerEl.innerHTML =
  '<div class="dr-h"><div class="a-ic" style="background:'+a.tint+';color:'+a.tc+'">'+a.name[0]+'</div><b>'+a.name+'</b><span class="dim mono" style="margin-left:8px">'+a.id+'</span>'+(a.en?'<span class="tag s">参与构建</span>':'<span class="tag c">已禁用</span>')+'<span class="x">×</span></div>'+
  '<div class="dr-b">'+
    '<div class="sect"><div class="s-t">这个 Agent 能干什么</div><div class="ai-body" style="font-size:13px">'+a.long+'</div></div>'+
    '<div class="sect"><div class="s-t">Skills 能力清单<span class="dim" style="font-weight:400;margin-left:6px">'+a.skills.length+' 项</span></div>'+
      a.skills.map(s=>'<div class="skill-item"><span class="mono">'+s[0]+'</span><span class="dim">'+s[1]+'</span></div>').join('')+
    '</div>'+
    '<div class="sect"><div class="s-t">在线安装（npm）<span class="tag r" style="margin-left:6px">'+pkgName(a)+'</span></div>'+
      '<div class="cmd"><span class="mono dim">$</span><span class="mono txt">'+npmCmd+'</span><button class="btn sm" data-cmd="'+npmCmd+'">复制</button></div>'+
      '<div class="hint" style="margin-top:10px">在线包发布于 npm registry，不含 Python wheels，体积小（'+a.sizeOn+'）；生产环境建议使用架构 dist-tag（x86-test / arm-test），latest 固定不动。</div>'+
      '<div class="actions" style="margin-top:10px"><button class="btn sm primary" data-dl-pick="'+a.id+'" data-pre="online">下载在线包</button></div>'+
    '</div>'+
    '<div class="sect"><div class="s-t">离线安装（构建服务器目录）</div>'+
      '<div class="cmd"><span class="mono dim">$</span><span class="mono txt">'+scpCmd+'</span><button class="btn sm" data-cmd="'+scpCmd+'">复制</button></div>'+
      '<div class="hint" style="margin-top:10px">离线包归档于 Jenkins Artifacts 目录 <span class="mono">/home/witty-agents-jenkins/artifacts/'+a.id+'/'+a.ver+'/</span>，含 Python wheels（'+a.sizeOff+'），适用于无外网环境；保留最近 10 次构建产物。</div>'+
      '<div class="actions" style="margin-top:10px"><button class="btn sm primary" data-dl-pick="'+a.id+'" data-pre="offline">下载离线包</button></div>'+
    '</div>'+
    '<div class="sect"><div class="s-t">增量构建前缀 changedPathPrefixes</div>'+
      '<div class="chips"><span class="chip">prefix <b>'+a.prefix+'</b></span><span class="chip">ci/agent.json</span><span class="chip">dir <b>'+a.dir+'/</b></span></div>'+
      '<div class="actions" style="margin-top:12px"><span class="ai-icon" data-ai-prefix="'+a.id+'">AI 前缀检测</span></div>'+
    '</div>'+
  '</div>'+
  '<div class="dr-f"><button class="btn" data-go="builds.html">构建历史</button><button class="btn primary" data-build-inline="'+a.id+'">发起构建</button></div>';
  document.body.appendChild(agentDrawerEl);
  raf(()=>{ agentDrawerEl.classList.add('show'); let ov=$('#drawerOverlay'); if(!ov){ ov=document.createElement('div'); ov.className='overlay'; ov.id='drawerOverlay'; document.body.appendChild(ov); ov.onclick=()=>{ closeDrawer(); closeAgentDrawer(); }; } ov.classList.add('show'); });
  agentDrawerEl.querySelector('.x').onclick = closeAgentDrawer;
  agentDrawerEl.querySelectorAll('[data-cmd]').forEach(b=>b.onclick=()=>copyText(b.dataset.cmd, '安装命令'));
  agentDrawerEl.querySelectorAll('[data-dl-pick]').forEach(b=>b.onclick=()=>openDlPicker(b.dataset.dlPick, b.dataset.pre));
  agentDrawerEl.querySelectorAll('[data-ai-prefix]').forEach(b=>b.onclick=()=>toast('AI 检测（mock）：近 30 天 commit 未触及 '+b.dataset.aiPrefix+' 之外路径，当前 changedPathPrefixes 覆盖良好；新增 docs/ 子目录建议补前缀',''));
  agentDrawerEl.querySelector('[data-build-inline]').onclick = ()=>{ closeAgentDrawer(); openTriggerDrawer({agent:a.id}); };
}
function agentStats(){
  const m = {};
  AGENTS.forEach(a=>m[a.id] = {b:0, dl:a.dl||0});
  BUILDS.forEach(x=>{ if (m[x.agent]) m[x.agent].b++; });
  return m;
}
const STATUS = {s:{t:'成功',c:'s'},f:{t:'失败',c:'f'},r:{t:'运行中',c:'r'},c:{t:'已取消',c:'c'}};
let BUILDS = [
  {no:127, agent:'shennong-crash', p:{variant:'all',style:'organization',arch:'aarch64'}, by:'张伟', status:'f', dur:'14m32s', time:'今天 10:21', d:'2026-09-16'},
  {no:126, agent:'auto', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'s', dur:'18m05s', time:'今天 09:47', d:'2026-09-16'},
  {no:125, agent:'nl2sql', p:{variant:'online',style:'plain',arch:'native'}, by:'李娜', status:'s', dur:'8m41s', time:'今天 08:12', d:'2026-09-16'},
  {no:124, agent:'openeuler-ops', p:{variant:'offline',style:'organization',arch:'x86_64'}, by:'王强', status:'s', dur:'22m18s', time:'昨天 21:33', d:'2026-09-15'},
  {no:123, agent:'shennong-crash', p:{variant:'online',style:'plain',arch:'aarch64'}, by:'张伟', status:'s', dur:'9m02s', time:'昨天 19:05', d:'2026-09-15'},
  {no:122, agent:'auto', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'f', dur:'12m50s', time:'昨天 15:20', d:'2026-09-15'},
  {no:121, agent:'nl2sql', p:{variant:'all',style:'plain',arch:'native'}, by:'李娜', status:'c', dur:'—', time:'昨天 14:02', d:'2026-09-15'},
  {no:120, agent:'openeuler-ops', p:{variant:'default',style:'organization',arch:'native'}, by:'张伟', status:'s', dur:'16m37s', time:'昨天 10:44', d:'2026-09-15'},
  {no:119, agent:'shennong-crash', p:{variant:'online',style:'organization',arch:'aarch64'}, by:'张伟', status:'s', dur:'9m48s', time:'前天 22:10', d:'2026-09-14'},
  {no:118, agent:'auto', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'s', dur:'17m22s', time:'前天 09:15', d:'2026-09-14'},
  {no:117, agent:'nl2sql', p:{variant:'offline',style:'plain',arch:'aarch64'}, by:'王强', status:'s', dur:'20m11s', time:'3天前', d:'2026-09-13'},
  {no:116, agent:'openeuler-ops', p:{variant:'online',style:'organization',arch:'native'}, by:'李娜', status:'f', dur:'7m35s', time:'3天前', d:'2026-09-13'},
  {no:115, agent:'auto', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'s', dur:'18m40s', time:'4天前', d:'2026-09-12'},
  {no:114, agent:'shennong-crash', p:{variant:'all',style:'organization',arch:'x86_64'}, by:'张伟', status:'s', dur:'25m03s', time:'4天前', d:'2026-09-12'},
  {no:113, agent:'nl2sql', p:{variant:'default',style:'plain',arch:'native'}, by:'李娜', status:'s', dur:'11m26s', time:'5天前', d:'2026-09-11'},
  {no:112, agent:'auto', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'f', dur:'13m18s', time:'5天前', d:'2026-09-11'},
  {no:111, agent:'openeuler-ops', p:{variant:'online',style:'plain',arch:'native'}, by:'王强', status:'s', dur:'8m55s', time:'6天前', d:'2026-09-10'},
  {no:110, agent:'shennong-crash', p:{variant:'online',style:'organization',arch:'aarch64'}, by:'张伟', status:'s', dur:'9m12s', time:'6天前', d:'2026-09-10'},
  {no:109, agent:'auto', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'s', dur:'17m58s', time:'7天前', d:'2026-09-09'},
  {no:108, agent:'nl2sql', p:{variant:'all',style:'plain',arch:'native'}, by:'李娜', status:'s', dur:'14m47s', time:'7天前', d:'2026-09-09'},
  {no:107, agent:'openeuler-ops', p:{variant:'offline',style:'organization',arch:'x86_64'}, by:'王强', status:'s', dur:'21m09s', time:'8天前', d:'2026-09-08'},
  {no:106, agent:'shennong-crash', p:{variant:'default',style:'organization',arch:'native'}, by:'张伟', status:'c', dur:'—', time:'8天前', d:'2026-09-08'},
  {no:105, agent:'auto', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'s', dur:'16m33s', time:'9天前', d:'2026-09-07'},
  {no:104, agent:'log-detection', p:{variant:'online',style:'plain',arch:'native'}, by:'李娜', status:'s', dur:'6m12s', time:'12天前', d:'2026-09-06'},
  {no:103, agent:'perf-analyzer', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'s', dur:'9m47s', time:'12天前', d:'2026-09-06'},
  {no:102, agent:'security-scan', p:{variant:'default',style:'organization',arch:'native'}, by:'王强', status:'f', dur:'5m28s', time:'13天前', d:'2026-09-05'},
  {no:101, agent:'crash-report', p:{variant:'online',style:'plain',arch:'native'}, by:'张伟', status:'s', dur:'4m55s', time:'13天前', d:'2026-09-05'},
  {no:100, agent:'compat-matrix', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'s', dur:'7m20s', time:'13天前', d:'2026-09-05'},
  {no:99, agent:'kernel-dataset', p:{variant:'offline',style:'organization',arch:'x86_64'}, by:'李娜', status:'s', dur:'18m06s', time:'14天前', d:'2026-09-04'},
  {no:98, agent:'sched-diagnosis', p:{variant:'default',style:'plain',arch:'native'}, by:'张伟', status:'c', dur:'—', time:'14天前', d:'2026-09-04'},
  {no:97, agent:'docs-writer', p:{variant:'default',style:'organization',arch:'native'}, by:'pollSCM', status:'s', dur:'3m41s', time:'14天前', d:'2026-09-04'},
  {no:96, agent:'log-detection', p:{variant:'default',style:'plain',arch:'native'}, by:'李娜', status:'s', dur:'5m03s', time:'14天前', d:'2026-09-04'}
];
let USERS = [
  {u:'zhangwei', n:'张伟', r:'系统管理员', on:true, t:'今天 10:18'},
  {u:'lina', n:'李娜', r:'项目管理员', on:true, t:'今天 08:05'},
  {u:'wangqiang', n:'王强', r:'开发成员', on:true, t:'昨天 21:30'},
  {u:'zhaojing', n:'赵静', r:'开发成员', on:false, t:'7天前'},
  {u:'sunliu', n:'孙刘', r:'只读访客', on:true, t:'昨天 14:20'},
  {u:'chenmeng', n:'陈萌', r:'只读访客', on:false, t:'30天前'}
];
let AUDIT = [
  {t:'今天 10:38', a:'张伟 × Agent', ai:true, e:'AI 诊断构建日志', r:'构建 #127'},
  {t:'今天 10:22', a:'张伟', e:'触发构建', r:'构建 #127（shennong-crash / all / aarch64）'},
  {t:'今天 09:47', a:'pollSCM', e:'自动构建（commit a1b2c3d）', r:'构建 #126'},
  {t:'昨天 22:40', a:'张伟 × Agent', ai:true, e:'AI 建议应用（高危·人审通过）', r:'PYPI_INDEX_URL 默认值变更'},
  {t:'昨天 21:35', a:'王强', e:'下载 Artifacts', r:'offline 包 witty-agent-openeuler-ops-1.2.0.tgz'},
  {t:'昨天 19:12', a:'张伟', e:'发布确认（CONFIRM_PUBLIC_PUBLISH）', r:'witty-agent-shennong@0.10.5-ci.aarch64.0 / arm-test'},
  {t:'昨天 18:55', a:'张伟 × Agent', ai:true, e:'AI 低危代执行：重跑构建', r:'构建 #123'},
  {t:'昨天 15:33', a:'—', e:'构建失败告警通知', r:'构建 #122'},
  {t:'昨天 14:03', a:'李娜', e:'取消构建', r:'构建 #121'},
  {t:'3天前 11:20', a:'李娜', e:'项目成员角色变更', r:'wangqiang: viewer → developer'},
  {t:'4天前 09:02', a:'张伟', e:'修改构建默认参数', r:'AGENT=auto / VARIANT=default'},
  {t:'5天前 16:44', a:'张伟', e:'登录', r:'10.8.12.30'}
];
const NOTIFS = [
  {c:'#f56c6c', t:'构建 #127 失败：Artifact Gates 阶段 SHA-256 校验不通过', s:'10 分钟前'},
  {c:'#e6a23c', t:'发布 #31 SHA-256 比对不一致，已标记失败待人工核查', s:'昨天 19:20'},
  {c:'#409eff', t:'pollSCM 检测到新提交，自动构建 #126 已完成', s:'今天 09:47'}
];
const STAGES = [
  {id:'init', n:'Initialize Parameters', d:'3s', st:'done'},
  {id:'plan', n:'Resolve Build Plan', d:'5s', st:'done'},
  {id:'prep', n:'Prepare Agents', d:'1m12s', st:'done'},
  {id:'assets', n:'Prepare Assets', d:'2m40s', st:'done'},
  {id:'deps', n:'Install Build Dependencies', d:'3m05s', st:'done'},
  {id:'validate', n:'Validate Agents', d:'1m48s', st:'done'},
  {id:'build', n:'Build Packages', d:'2m33s', st:'done'},
  {id:'gates', n:'Artifact Gates', d:'41s', st:'fail'},
  {id:'contract', n:'Install Contract Checks', d:'—', st:'skip'},
  {id:'install', n:'Real Install Flow', d:'—', st:'skip'},
  {id:'publish', n:'Publish to npm', d:'—', st:'skip'}
];

const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView){ Element.prototype.scrollIntoView = function(){}; }
const raf = (typeof requestAnimationFrame === 'function') ? (fn)=>requestAnimationFrame(fn) : (fn)=>setTimeout(fn, 0);
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function getRole(){ return localStorage.getItem('proto-role') || 'admin'; }
function setRole(r){
  localStorage.setItem('proto-role', r);
  document.body.dataset.role = r;
  const sel = $('#roleSel'); if (sel) sel.value = r;
  const lab = $('#roleLab'); if (lab) lab.textContent = ROLES[r];
  toast('已切换为「' + ROLES[r] + '」视角，页面元素显隐随权限变化', 's');
}

function toast(msg, type){
  let box = $('.toasts');
  if (!box){ box = document.createElement('div'); box.className = 'toasts'; document.body.appendChild(box); }
  const t = document.createElement('div');
  t.className = 'toast ' + (type||'');
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(()=>{ t.style.opacity='0'; t.style.transition='.3s'; setTimeout(()=>t.remove(),300); }, 2600);
}

function confirmBox(title, html, opts){
  opts = opts || {};
  closeModal();
  const ov = document.createElement('div');
  ov.className = 'overlay show'; ov.dataset.modalOverlay = '1';
  const m = document.createElement('div');
  m.className = 'modal show';
  m.innerHTML = '<div class="m-h"><b>'+title+'</b><span class="x">×</span></div><div class="m-b">'+html+'</div><div class="m-f"></div>';
  const f = m.querySelector('.m-f');
  const cancel = document.createElement('button'); cancel.className='btn'; cancel.textContent = opts.cancelText || '取消';
  const ok = document.createElement('button'); ok.className = 'btn ' + (opts.danger ? 'danger' : 'primary'); ok.textContent = opts.okText || '确定';
  const dismiss = ()=>{ ov.remove(); };
  cancel.onclick = ()=>{ dismiss(); opts.onCancel && opts.onCancel(); };
  ok.onclick = ()=>{ const keep = opts.onOk && opts.onOk(); if (keep !== false) dismiss(); };
  m.querySelector('.x').onclick = closeModal;
  ov.onclick = e => { if (e.target === ov) closeModal(); };
  f.appendChild(cancel); f.appendChild(ok);
  ov.appendChild(m); document.body.appendChild(ov);
}
function closeModal(){ $$('[data-modal-overlay]').forEach(e=>e.remove()); }

const ARTIFACTS = {
  'build-plan.json': {title:'ci-artifacts/build-plan.json', data:{schemaVersion:1, generatedAt:'2026-09-16T10:21:12+08:00', agent:'shennong-crash', variants:['online','offline'], packageStyle:'organization', targetArch:'aarch64', publish:false, plan:[{id:'shennong-crash', reason:'explicit AGENT parameter', matchedPrefix:'shennong-crash-agent/', variants:['online','offline']}], skipped:[{id:'nl2sql', reason:'prefix not in changedPathPrefixes'}]}},
  'online-package-report.json': {title:'shennong-crash-agent/artifacts/online-package-report.json', data:{agent:'shennong-crash', variant:'online', package:'@openeuler/witty-agent-shennong', version:'0.10.5-ci.aarch64.0', sizeBytes:4404019, fileCount:38, sha256:'497783c6d7c4c308762134828c2102c4b67497a7e9a20041b82d7471231ed997', gates:{manifest:true, distTagPolicy:'warn:latest-overridden-by-policy', sizeLimit:true}, build:{no:127, commit:'a1b2c3d', node:'aarch64-native'}}},
  'npm-publish-smoke-summary.json': {title:'ci-artifacts/npm-publish-smoke-summary.json', data:{package:'witty-agent-shennong', version:'0.10.5-ci.aarch64.0', distTag:'arm-test', registry:'https://registry.npmjs.org/', steps:{gates:'pass', pack:'pass', publish:'pass', registryVisibility:{waitSeconds:3, status:'pass'}, redownload:'pass', sha256Compare:{candidate:'497783c6…ed997', redownloaded:'973bf843…eb687', match:false, status:'fail'}}, latestBefore:'0.10.3', latestAfter:'0.10.3', conclusion:'fail', action:'manual-review-required'}},
  'manifest.json': {title:'ci-artifacts/npm-download/manifest.json', data:{fetchedAt:'2026-09-15T19:12:09+08:00', tarball:'https://registry.npmjs.org/witty-agent-shennong/-/witty-agent-shennong-0.10.5-ci.aarch64.0.tgz', integrity:'sha512-973bf843c7de81f627d5ea635ca0b56d6c73e7dd98560471553a903fcdeeb687', sizeBytes:4398210, distTagResolved:'arm-test'}}
};
function hlJSON(obj){
  return esc(JSON.stringify(obj, null, 2))
    .replace(/"([^"\\]+)":/g, '<span class="j-k">"$1"</span>:')
    .replace(/: "((?:[^"\\]|\\.)*)"/g, ': <span class="j-s">"$1"</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="j-n">$1</span>')
    .replace(/: (true|false|null)/g, ': <span class="j-b">$1</span>');
}
function jsonViewer(name){
  const a = ARTIFACTS[name];
  if (!a){ toast('该产物为二进制包，无 JSON 预览（mock）','w'); return; }
  closeModal();
  const ov = document.createElement('div');
  ov.className = 'overlay show'; ov.dataset.modalOverlay = '1';
  const m = document.createElement('div');
  m.className = 'modal show'; m.style.width = '720px';
  m.innerHTML = '<div class="m-h"><b class="mono" style="font-size:13.5px">'+a.title+'</b><span class="x">×</span></div>'+
    '<div class="m-b"><pre class="json-view">'+hlJSON(a.data)+'</pre></div>'+
    '<div class="m-f"><button class="btn" id="jvDl">下载原文</button><button class="btn primary" id="jvClose">关闭</button></div>';
  ov.appendChild(m); document.body.appendChild(ov);
  ov.onclick = e => { if (e.target === ov) closeModal(); };
  m.querySelector('.x').onclick = closeModal;
  m.querySelector('#jvClose').onclick = closeModal;
  m.querySelector('#jvDl').onclick = ()=>toast('开始下载 '+a.title+'（mock）','s');
}

function aiLoad(panelId, bodyId, html, bind, loadingText){
  const panel = $('#'+panelId);
  panel.classList.remove('hidden');
  const body = $('#'+bodyId);
  body.innerHTML = '<div class="ai-loading"><span class="bar"></span>'+(loadingText||'AI 分析中：提取特征 → 关联上下文 → 匹配已知模式…')+'</div>';
  setTimeout(()=>{ body.innerHTML = html; bind && bind(); }, 520);
}
const aiMetrics = ms => '<div class="ai-metrics">'+ms.map(m=>'<div class="ai-metric '+(m.t||'')+'"><div class="k">'+m.k+'</div><div class="v">'+m.v+'</div></div>').join('')+'</div>';
const aiConf = (pct, note) => '<div class="ai-conf">置信度<span class="track"><span class="fill" style="display:block;width:'+pct+'%"></span></span><b>'+pct+'%</b><span>'+(note||'')+'</span></div>';

const AG_DIAG = {
  'shennong-crash': {m:[{k:'最近构建',v:'失败 #127',t:'bad'},{k:'根因',v:'wheel SHA-256',t:'bad'},{k:'online 变体',v:'通过',t:'good'},{k:'停用风险',v:'低'}], body:'失败集中在 <b>Artifact Gates</b>：offline wheel 与归档包哈希不一致（疑似 pypi 镜像回源重建）。online 链路 7 日 100% 通过，建议先以 online 变体发布，镜像治理并行推进。', sugs:['以 VARIANT=online 触发构建并走发布门禁','应用项目设置中的 PYPI_INDEX_URL 切换建议（需人审）'], pct:82},
  'nl2sql': {m:[{k:'近 10 次构建',v:'10 通过',t:'good'},{k:'平均耗时',v:'11m06s'},{k:'风险项',v:'无',t:'good'}], body:'近 10 次构建全部通过，无失败模式；变更频率低（月均 2 次 MR），门禁指标稳定。无需处置。', sugs:['保持当前构建默认参数即可'], pct:91},
  'openeuler-ops': {m:[{k:'最近构建',v:'成功 #124',t:'good'},{k:'offline 体积',v:'386MB',t:'bad'},{k:'P95 偏差',v:'+64%',t:'bad'}], body:'offline 产物体积 386MB，显著高于同类 P95（236MB）。归因：wheels 未裁剪平台无关依赖，且 OCR 模型缓存命中率仅 62%。', sugs:['在 ci/agent.json 中收窄 offline wheels 收集范围','提升构建节点 OCR_MODEL_CACHE_DIR 命中率（缓存预热）'], pct:76},
  'xlite-perf-optimizer': {m:[{k:'状态',v:'禁用构建 30 天'},{k:'关联活动',v:'无',t:'bad'},{k:'最近版本',v:'0.4.1'}], body:'禁用构建 30 天且无关联分支活动。平台不提供删除操作——如确认不再演进，可在仓库侧评估归档方案；若后续恢复构建，建议先跑一次增量构建验证 changedPathPrefixes 覆盖。', sugs:['保持禁用状态，等待仓库侧归档决策','恢复构建前先执行增量构建验证注册信息有效性'], pct:68}
};
function renderHealthTable(){
  $('#agfBody').innerHTML = AGENTS.map(a=>
    '<tr data-ag-row data-name="'+a.id+' '+a.name+'" data-en="'+(a.en?'on':'off')+'" data-last="'+a.last+'">'+
    '<td class="mono">'+a.id+'</td><td>'+(a.en?'<span class="tag s">参与构建</span>':'<span class="tag c">已禁用</span>')+'</td>'+
    '<td>'+statusTag(a.last)+'</td><td class="mono">'+a.ver+'</td>'+
    '<td><button class="btn sm ai" data-agdiag="'+a.id+'">AI 诊断</button></td></tr>').join('');
}

function bindRowFilter(qId, conds, rowSel, countId){  const q = $('#'+qId);
  const rows = ()=> $$(rowSel);
  const apply = ()=>{
    const text = q ? q.value.trim().toLowerCase() : '';
    let shown = 0;
    rows().forEach(r=>{
      let ok = !text || (r.dataset.name || '').toLowerCase().includes(text);
      conds.forEach(c=>{ if ($('#'+c.id).value !== 'all' && r.dataset[c.key] !== $('#'+c.id).value) ok = false; });
      r.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    const cnt = $('#'+countId);
    if (cnt) cnt.textContent = shown + ' / ' + rows().length;
  };
  q && (q.oninput = apply);
  conds.forEach(c=>{ $('#'+c.id).onchange = apply; });
  apply();
}

function agentDiagModal(id){
  const d = AG_DIAG[id];
  const st = agentStats()[id] || {b:0, dl:0};
  const a = AGENTS.find(x=>x.id===id);
  if (!d && a){
    confirmBox('AI 诊断 · '+id,
      aiMetrics([{k:'构建次数',v:String(st.b)},{k:'累计下载',v:String(st.dl)},{k:'状态',v:a.en?'参与构建':'已禁用',t:a.en?'good':''},{k:'最近版本',v:a.ver}])+
      '<div class="ai-sec">结论</div><div class="ai-body">该 Agent 为 mock 演示数据（未纳入深度诊断知识库）。基于通用构建遥测：构建记录 '+st.b+' 次、产物累计下载 '+st.dl+' 次，无异常聚集模式。</div>'+
      '<div class="ai-sec">建议</div><div class="ai-sug"><span class="n">1</span>保持当前默认构建参数，观察后续增量构建稳定性</div>'+
      aiConf(60,'通用遥测，无专项知识库支撑'),
      {okText:'知道了'});
    return;
  }
  if (!d) { toast('暂无该 Agent 的诊断数据（mock）','w'); return; }
  const html = aiMetrics(d.m) +
    '<div class="ai-sec">结论</div><div class="ai-body">'+d.body+'</div>' +
    '<div class="ai-sec">建议</div>' + d.sugs.map((s,i)=>'<div class="ai-sug"><span class="n">'+(i+1)+'</span>'+s+'</div>').join('') +
    aiConf(d.pct, '基于构建历史与变更轨迹');
  confirmBox('AI 诊断 · '+id, html, {okText:'知道了'});
}

function navShell(){
  const body = document.body;
  const shell = body.dataset.shell;
  if (!shell || shell === 'none') return;
  const page = body.dataset.page || '';
  const CRUMBS = {dashboard:['工作台','dashboard.html'], overview:['witty-agents / 概览','project-overview.html'], agents:['witty-agents / Agent 管理','agents.html'], builds:['witty-agents / 构建流水线','builds.html'], 'build-detail':['witty-agents / 构建流水线 / #127','build-detail.html'], release:['witty-agents / 发布管理 / #31','release-detail.html'], users:['管理 / 用户管理','users.html'], audit:['管理 / 审计日志','audit.html']};
  const projActive = ['overview','agents','builds','build-detail','release'].includes(page);
  const role = getRole();
  let top = '<div class="topbar"><div class="topbar-left"><div class="logo" data-go="dashboard.html">witty-agent-factor</div>';
  top += '<nav class="topnav">';
  top += '<a href="dashboard.html" class="'+(page==='dashboard'?'active':'')+'">工作台</a>';
  top += '<a href="project-overview.html" class="'+(projActive?'active':'')+'">项目</a>';
  top += '<a href="users.html" class="'+((page==='users'||page==='audit')?'active':'')+' admin-only">管理</a>';
  top += '</nav>';
  if (CRUMBS[page]) top += '<div class="crumb"><b>'+CRUMBS[page][0]+'</b></div>';
  top += '</div>';
  top += '<div class="top-right">';
  top += '<div class="role-switch"><span class="rl">视角</span><select id="roleSel"><option value="admin">项目管理员</option><option value="developer">开发成员</option><option value="viewer">只读访客</option></select></div>';
  top += '<div class="tb-icon" id="bellBtn">通知<span class="badge">'+NOTIFS.length+'</span><div class="dropdown" id="notifDd"><div class="dd-title">通知<span class="link" data-toast="通知已全部标记为已读（mock）">全部已读</span></div>';
  NOTIFS.forEach(n=>{ top += '<div class="dd-item"><span class="dot" style="background:'+n.c+'"></span><div><div class="t">'+n.t+'</div><div class="s">'+n.s+'</div></div></div>'; });
  top += '</div></div>';
  top += '<div class="tb-icon" id="userBtn" style="padding:0"><div class="avatar">张</div><div class="dropdown user-dd" id="userDd">';
  top += '<div class="u-head"><b>张伟</b><span id="roleLab">'+ROLES[role]+'</span></div>';
  top += '<div class="u-row" data-toast="修改密码（原型演示：已打开修改密码弹窗逻辑）">修改密码</div>';
  top += '<div class="u-row" data-go="login.html">退出登录</div>';
  top += '</div></div></div></div>';
  body.insertAdjacentHTML('afterbegin', top);
  if (shell === 'project'){
    const side = document.createElement('div'); side.className = 'layout';
    const items = [
      ['overview','project-overview.html','概览'],
      ['agents','agents.html','Agent 管理'],
      ['builds','builds.html','构建流水线'],
      ['release','release-detail.html','发布管理']
    ];
    let sh = '<div class="grp">witty-agents</div>';
    items.forEach(it=>{
      const on = it[0]===page || (it[0]==='builds' && page==='build-detail');
      sh += '<a class="item'+(on?' active':'')+'" href="'+it[1]+'"><span>'+it[2]+'</span></a>';
    });
    side.innerHTML = '<aside class="sidebar">'+sh+'</aside>';
    const content = body.querySelector('.content');
    body.insertBefore(side, content);
    side.appendChild(content);
  } else {
    const wrap = document.createElement('div'); wrap.className = 'plain-wrap';
    const content = body.querySelector('.content');
    body.insertBefore(wrap, content); wrap.appendChild(content);
  }
  body.insertAdjacentHTML('beforeend','<div class="overlay" id="drawerOverlay"></div>');
  $('#drawerOverlay').onclick = ()=>{ closeDrawer(); closeAgentDrawer(); };
  const rs = $('#roleSel'); rs.value = role;
  rs.onchange = e => setRole(e.target.value);
  body.dataset.role = role;
  $('#bellBtn').onclick = e => { e.stopPropagation(); $('#notifDd').classList.toggle('show'); $('#userDd').classList.remove('show'); };
  $('#userBtn').onclick = e => { e.stopPropagation(); $('#userDd').classList.toggle('show'); $('#notifDd').classList.remove('show'); };
  document.addEventListener('click', ()=>{ const n=$('#notifDd'),u=$('#userDd'),c=$('#cfDd'); if(n)n.classList.remove('show'); if(u)u.classList.remove('show'); if(c)c.classList.remove('show'); });
  document.addEventListener('keydown', e=>{
    if (e.key === 'Escape'){ closeDrawer(); closeAgentDrawer(); closeModal(); const n=$('#notifDd'),u=$('#userDd'),c=$('#cfDd'); if(n)n.classList.remove('show'); if(u)u.classList.remove('show'); if(c)c.classList.remove('show'); }
  });
  document.addEventListener('click', e => {
    const go = e.target.closest('[data-go]');
    if (go){ location.href = go.dataset.go; }
    const tt = e.target.closest('[data-toast]');
    if (tt){ toast(tt.dataset.toast, tt.dataset.type||''); }
    const art = e.target.closest('[data-art]');
    if (art){ jsonViewer(art.dataset.art); }
    const agd = e.target.closest('[data-agdiag]');
    if (agd){ agentDiagModal(agd.dataset.agdiag); }
    const fh = e.target.closest('.fold .f-h');
    if (fh){ fh.parentElement.classList.toggle('open'); }
  });
}

let drawerEl = null;
function closeDrawer(){ if (drawerEl) drawerEl.classList.remove('show'); const ov=$('#drawerOverlay'); ov && ov.classList.remove('show'); }
function openTriggerDrawer(prefill){
  if (drawerEl) drawerEl.remove();
  prefill = prefill || {};
  drawerEl = document.createElement('div'); drawerEl.className = 'drawer';
  const agOpts = AGENTS.map(a=>a.id);
  const mode = prefill.agent==='all' ? 'full' : (prefill.agent && prefill.agent!=='auto' ? 'single' : 'incr');
  drawerEl.innerHTML =
  '<div class="dr-h"><b>触发构建</b><span class="dim mono" style="margin-left:10px">Job: witty-agent-package-ci</span><span class="x">×</span></div>'+
  '<div class="dr-b">'+
    '<div class="sect"><div class="s-t"><span class="n">1</span>构建范围</div>'+
      '<div class="mode-row">'+
        '<div class="mode-opt" data-mode="incr"><b>增量构建</b><span>仅构建命中变更路径前缀（changedPathPrefixes）的 Agent · AGENT=auto</span></div>'+
        '<div class="mode-opt" data-mode="full"><b>全量构建</b><span>构建全部启用中的 Agent · AGENT=all</span></div>'+
        '<div class="mode-opt" data-mode="single"><b>指定 Agent</b><span>仅构建选定的单个 Agent</span></div>'+
      '</div>'+
      '<div class="fi" id="fAgentWrap" style="display:none"><label>目标 Agent <i>*</i></label><select class="inp" id="fAgent">'+agOpts.map(o=>'<option '+(o===prefill.agent?'selected':'')+'>'+o+'</option>').join('')+'</select></div></div>'+
    '<div class="sect"><div class="s-t"><span class="n">2</span>变体与架构</div><div class="form-grid">'+
      '<div class="fi"><label>VARIANT</label><select class="inp" id="fVariant">'+['default','online','offline','all'].map(o=>'<option '+(o===(prefill.variant||'default')?'selected':'')+'>'+o+'</option>').join('')+'</select></div>'+
      '<div class="fi"><label>PACKAGE_STYLE</label><select class="inp" id="fStyle">'+['organization','plain'].map(o=>'<option '+(o===(prefill.style||'organization')?'selected':'')+'>'+o+'</option>').join('')+'</select></div>'+
      '<div class="fi full"><label>TARGET_ARCH</label><select class="inp" id="fArch">'+['native','x86_64','aarch64'].map(o=>'<option '+(o===(prefill.arch||'native')?'selected':'')+'>'+o+'</option>').join('')+'</select></div>'+
      '<div class="full hint" id="archHint" style="display:none">offline 变体要求 native 构建节点架构与 TARGET_ARCH 一致，否则 Real Install 阶段将失败。</div>'+
    '</div></div>'+
    '<div class="sect"><div class="s-t"><span class="n">3</span>验证</div>'+
      '<label class="sw-row" style="display:flex;gap:10px;align-items:center;margin-bottom:10px"><span class="switch"><input type="checkbox" checked id="fReal"><span class="sl"></span></span><span>真实安装链路验证（install → setup×2 → configure×2 → remove → stop → uninstall）</span></label>'+
      '<label style="display:flex;gap:10px;align-items:center"><span class="switch"><input type="checkbox" checked id="fStrict"><span class="sl"></span></span><span>离线网络强校验（STRICT_OFFLINE_NETWORK_CHECK）</span></label></div>'+
    '<div class="fold"><div class="f-h"><span class="arr">▶</span>高级选项</div><div class="f-b"><div class="form-grid">'+
      '<div class="fi"><label>PYTHON_BIN</label><input class="inp" value="python3.11"></div>'+
      '<div class="fi"><label>PYPI_INDEX_URL</label><input class="inp" value="https://mirrors.huaweicloud.com/repository/pypi/simple"></div>'+
      '<div class="fi full"><label>OCR_MODEL_CACHE_DIR</label><input class="inp" value="/home/witty-agents-jenkins/ocr-model-cache"></div>'+
    '</div></div></div>'+
    '<div class="fold admin-only"><div class="f-h"><span class="arr">▶</span>发布选项 <span class="tag w">仅项目管理员</span></div><div class="f-b"><div class="form-grid">'+
      '<div class="fi"><label>PUBLISH</label><label class="switch" style="margin-top:4px"><input type="checkbox" id="fPublish"><span class="sl"></span></label></div>'+
      '<div class="fi"><label>NPM_CREDENTIAL_ID</label><input class="inp" value="npm-token"></div>'+
      '<div class="fi"><label>NPM_REGISTRY</label><input class="inp" value="https://registry.npmjs.org/"></div>'+
      '<div class="fi"><label>NPM_DIST_TAG</label><input class="inp" value="latest"></div>'+
      '<div class="fi full"><label>GIT_CREDENTIAL_ID</label><input class="inp" value="" placeholder="留空则版本 bump 仅保留在 workspace"></div>'+
      '<div class="full hint">发布选项受 REL-01 门禁约束：仅官方仓库 master 提交、全变体通过、prerelease 版本、dist-tag 禁止 latest（正式发布自动替换为 x86-test / arm-test）。</div>'+
    '</div></div></div>'+
    '<div class="ai-panel" id="drawerAi" style="display:none"><div class="ai-head"><span class="ai-badge">AI</span><span class="ai-title">推荐参数</span></div>'+
    '<div class="ai-body">基于最近 3 次失败（<b>SHA-256 mismatch</b>）与本次变更内容，建议：<span class="chip">VARIANT=<b>online</b></span><span class="chip">TARGET_ARCH=<b>aarch64</b></span><span class="chip">PACKAGE_STYLE=<b>plain</b></span><br>理由 ▸ online 产物不携带 Python wheels，可绕开 offline wheel 打包差异；aarch64 与失败构建同架构便于比对。<div class="ai-actions"><button class="btn sm primary" id="aiFill">应用填充</button><button class="btn sm" data-toast="已反馈：一般（会用于优化推荐模型）">不采用</button></div></div></div>'+
    '<div style="text-align:center;margin:2px 0 6px"><span class="ai-icon" id="aiShow">AI 推荐参数</span></div>'+
  '</div>'+
  '<div class="dr-f"><button class="btn" id="drCancel">取消</button><button class="btn primary" id="drOk">触发构建</button></div>';
  document.body.appendChild(drawerEl);
  raf(()=>{
    drawerEl.classList.add('show');
    let ov = $('#drawerOverlay');
    if (!ov){ ov = document.createElement('div'); ov.className = 'overlay'; ov.id = 'drawerOverlay'; document.body.appendChild(ov); ov.onclick = closeDrawer; }
    ov.classList.add('show');
  });
  drawerEl.querySelector('.x').onclick = closeDrawer;
  $('#drCancel').onclick = closeDrawer;
  $('#aiShow').onclick = ()=>{
    const p = $('#drawerAi');
    p.style.display = p.style.display === 'none' ? '' : 'none';
    toast(p.style.display === 'none' ? '已收起 AI 推荐' : 'AI 推荐已生成（基于最近 3 次失败与变更内容）');
  };
  const vSel = $('#fVariant'), aHint = $('#archHint');
  const chk = ()=>{ aHint.style.display = vSel.value==='offline' ? '' : 'none'; };
  vSel.onchange = chk; chk();
  let curMode = mode;
  const applyMode = m=>{
    curMode = m;
    $$('.mode-opt').forEach(el=>el.classList.toggle('sel', el.dataset.mode===m));
    $('#fAgentWrap').style.display = m==='single' ? '' : 'none';
  };
  $$('.mode-opt').forEach(el=>el.onclick=()=>applyMode(el.dataset.mode));
  applyMode(mode);
  const agentParam = ()=> curMode==='incr' ? 'auto' : curMode==='full' ? 'all' : $('#fAgent').value;
  const modeLabel = ()=> curMode==='incr' ? '增量（AGENT=auto）' : curMode==='full' ? '全量（AGENT=all）' : '指定 '+$('#fAgent').value;
  $('#drOk').onclick = ()=>{
    if (curMode==='single' && !$('#fAgent').value){ toast('请选择目标 Agent','w'); return; }
    toast('已触发构建 #128 · 范围：'+modeLabel()+' · VARIANT='+$('#fVariant').value+'。disableConcurrentBuilds：若已有排队构建将顺延', 's');
    setTimeout(closeDrawer, 400);
  };
  const showAi = ()=>{ $('#drawerAi').style.display=''; };
  if (prefill.showAi) showAi();
  const fill = ()=>{ $('#fVariant').value = prefill.variant||'online'; $('#fArch').value = prefill.arch||'aarch64'; $('#fStyle').value = prefill.style||'plain'; chk(); toast('已按 AI 推荐填充参数，请确认后手动提交（不自动触发）','s'); };
  drawerEl.querySelector('#aiFill') && (drawerEl.querySelector('#aiFill').onclick = fill);
  return {showAi, fill};
}

function statusTag(s){ const x = STATUS[s]; return '<span class="tag '+x.c+'">'+(s==='r'?'<span class="pulse"></span>':'')+x.t+'</span>'; }
function paramChips(p){ return '<span class="chip">V=<b>'+p.variant+'</b></span><span class="chip">S=<b>'+p.style+'</b></span><span class="chip">A=<b>'+p.arch+'</b></span>'; }

function filteredBuilds(){
  const st = $('#bFilterStatus').value, ag = $('#bFilterAgent').value, by = $('#bFilterBy').value;
  const d1 = $('#bDateFrom').value, d2 = $('#bDateTo').value;
  return BUILDS.filter(b=>
    (st==='all'||b.status===st) &&
    (ag==='all'||b.agent===ag) &&
    (by==='all'||b.by===by) &&
    (!d1 || b.d >= d1) &&
    (!d2 || b.d <= d2));
}
const fmtCN = d => { if (!d) return ''; const p = d.split('-'); return p[0]+'年'+p[1]+'月'+p[2]+'日'; };
function renderBuildsTable(){
  const list = filteredBuilds();
  const total = list.length, per = 8;
  const pages = Math.max(1, Math.ceil(total/per));
  const cur = Math.min(pages, parseInt($('#bPage').dataset.cur||'1'));
  $('#bPage').dataset.cur = cur;
  const slice = list.slice((cur-1)*per, cur*per);
  const tb = $('#buildsTbody');
  if (!slice.length){ tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text3);padding:30px">暂无匹配的构建记录</td></tr>'; }
  else tb.innerHTML = slice.map(b=>
    '<tr class="clickable" data-go="build-detail.html"><td class="link mono">#'+b.no+'</td><td class="mono">'+b.agent+'</td>'+
    '<td><div class="chips">'+paramChips(b.p)+'</div></td><td>'+b.by+'</td><td>'+statusTag(b.status)+'</td>'+
    '<td class="mono">'+b.dur+'</td><td class="dim">'+b.time+'</td>'+
    '<td onclick="event.stopPropagation()"><div class="actions">'+
      (b.status==='r' ? '<button class="btn sm danger" data-cancel="'+b.no+'">取消</button>' : '')+
      (b.status!=='r' ? '<button class="btn sm hide-viewer" data-rerun="'+b.no+'">重跑</button>' : '')+
      (b.status==='s' ? '<button class="btn sm" data-dlb="'+b.no+'">下载产物</button>' : '')+
    '</div></td></tr>').join('');
  const pg = $('#bPage');
  let h = '<button '+(cur<=1?'disabled':'')+' data-pg="'+(cur-1)+'">‹</button>';
  for (let i=1;i<=pages;i++) h += '<button class="'+(i===cur?'cur':'')+'" data-pg="'+i+'">'+i+'</button>';
  h += '<button '+(cur>=pages?'disabled':'')+' data-pg="'+(cur+1)+'">›</button>';
  h += '<span style="margin-left:8px">共 '+total+' 条 / '+pages+' 页</span>';
  pg.innerHTML = h;
  $$('[data-pg]').forEach(b=>b.onclick=()=>{ pg.dataset.cur=b.dataset.pg; renderBuildsTable(); });
  $$('[data-rerun]').forEach(b=>b.onclick=e=>{ e.stopPropagation(); confirmBox('重跑构建','将以与 <b class="mono">#'+b.dataset.rerun+'</b> 完全相同的参数创建新构建。',{okText:'重跑',onOk:()=>toast('已创建重跑构建（mock：新编号 #128）','s')}); });
  $$('[data-cancel]').forEach(b=>b.onclick=e=>{ e.stopPropagation(); confirmBox('取消构建','确定取消排队/运行中的构建 <b class="mono">#'+b.dataset.cancel+'</b>？此操作会终止 Jenkins Executor。',{danger:true,okText:'取消构建',onOk:()=>{ const t=BUILDS.find(x=>x.no==b.dataset.cancel); if(t){t.status='c';t.dur='—';} toast('构建 #'+b.dataset.cancel+' 已取消','w'); renderBuildsTable(); }}); });
  $$('[data-dlb]').forEach(b=>b.onclick=e=>{ e.stopPropagation(); const t=BUILDS.find(x=>x.no==b.dataset.dlb); toast('开始下载构建 #'+t.no+' 产物：'+(t.p.style==='organization'?'@openeuler/':'')+'witty-agent-'+t.agent+'-'+t.p.variant+'.tgz（mock，带权限校验的临时链接）','s'); });
}

function renderAgents(){
  const q = ($('#aSearch') ? $('#aSearch').value : '').toLowerCase();
  const st = $('#aFilterStatus').value;
  const list = AGENTS.filter(a=>(st==='all'|| (st==='on')===a.en) && (!q || (a.id+a.name+a.dir).toLowerCase().includes(q)));
  const box = $('#agentGrid');
  if (!list.length){ box.innerHTML = '<div class="card" style="grid-column:1/-1"><div class="card-b" style="text-align:center;color:var(--text3);padding:30px">没有匹配的 Agent</div></div>'; return; }
  box.innerHTML = list.map(a=>
    '<div class="agent-card clickable" data-open-agent="'+a.id+'" title="点击查看 Agent 详情（能力 / Skills / 安装方式）"><div class="a-top"><div class="a-ic" style="background:'+a.tint+';color:'+a.tc+'">'+a.name[0]+'</div>'+
    '<div class="a-tw"><div class="a-name">'+a.name+'</div><div class="a-id">'+a.id+'</div></div>'+
    '<span class="a-state"><span class="tag '+(a.en?'s':'c')+' admin-else">'+(a.en?'参与构建':'已禁用')+'</span>'+
    '<label class="switch admin-only" title="禁用构建（agents.json enabled=false，不删除目录）"><input type="checkbox" data-en="'+a.id+'" '+(a.en?'checked':'')+'><span class="sl"></span></label></span></div>'+
    '<div class="a-desc">'+a.desc+'</div>'+
    '<div class="a-meta"><span class="chip">v<b>'+a.ver+'</b></span><span class="chip">skills <b>'+a.skills.length+'</b></span><span class="chip">下载 <b>'+a.dl+'</b></span><span class="chip more" data-open-agent="'+a.id+'">详情 →</span></div>'+
    '<div class="a-foot">'+
    '<button class="btn sm primary hide-viewer" data-build="'+a.id+'">发起构建</button>'+
    (a.last==='s' ? '<button class="btn sm" data-dl-agent="'+a.id+'" title="在线包 / 离线包勾选下载">下载产物</button>' : '')+
    '<button class="btn sm" data-go="builds.html">构建历史</button></div></div>').join('');
  box.querySelectorAll('[data-open-agent]').forEach(el=>el.onclick=e=>{
    if (e.target.closest('button, a, label, .switch, input')) return;
    openAgentDrawer(el.dataset.openAgent);
  });
  $$('[data-en]').forEach(sw=>sw.onchange=()=>{ const a=AGENTS.find(x=>x.id===sw.dataset.en); a.en=sw.checked; toast('Agent '+a.id+' 已'+(a.en?'启用（enabled=true，将参与增量构建计划）':'禁用构建（enabled=false，不删除目录，不参与构建计划）'), sw.checked?'s':'w'); renderAgents(); });
  $$('[data-build]').forEach(b=>b.onclick=()=>openTriggerDrawer({agent:b.dataset.build}));
  $$('[data-dl-agent]').forEach(b=>b.onclick=()=>openDlPicker(b.dataset.dlAgent));
  $$('[data-ai-prefix]').forEach(b=>b.onclick=()=>toast('AI 检测（mock）：近 30 天 commit 未触及 '+b.dataset.aiPrefix+' 之外路径，当前 changedPathPrefixes 覆盖良好；新增 docs/ 子目录建议补前缀',''));
}

function renderUsers(){
  const tb = $('#usersTbody');
  tb.innerHTML = USERS.map((u,i)=>
    '<tr><td class="mono">'+u.u+'</td><td>'+u.n+'</td><td><span class="tag '+(u.r==='系统管理员'?'p':u.r==='项目管理员'?'r':u.r==='开发成员'?'s':'c')+'">'+u.r+'</span></td>'+
    '<td><label class="switch"><input type="checkbox" data-uon="'+i+'" '+(u.on?'checked':'')+'><span class="sl"></span></label></td>'+
    '<td class="dim">'+u.t+'</td><td><div class="actions">'+
    '<button class="btn sm" data-toast="重置密码邮件已发送（mock）">重置密码</button>'+
    '<button class="btn sm" data-toast="编辑用户（mock）">编辑</button>'+
    '</div></td></tr>').join('');
  $$('[data-uon]').forEach(sw=>sw.onchange=()=>{ const u=USERS[sw.dataset.uon]; confirmBox((sw.checked?'启用':'禁用')+'用户', sw.checked?'启用后 '+u.n+' 可正常登录。':'禁用后 '+u.n+' 的会话将被立即踢出。',{danger:!sw.checked, okText:sw.checked?'启用':'禁用', onOk:()=>{ u.on=sw.checked; toast(u.n+' 已'+(sw.checked?'启用':'禁用'), sw.checked?'s':'w'); }, onCancel:()=>{ sw.checked=!sw.checked; }}); });
}

function renderAudit(){
  const ev = $('#auFilterEv').value, onlyAi = $('#auOnlyAi').checked, q = ($('#auSearch')?$('#auSearch').value:'').toLowerCase();
  let list = AUDIT.filter(a=>(ev==='all'||a.e.includes(ev))&&(!onlyAi||a.ai)&&(!q||(a.a+a.e+a.r).toLowerCase().includes(q)));
  const tb = $('#auditTbody');
  if (!list.length){ tb.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text3);padding:30px">无匹配审计记录</td></tr>'; return; }
  tb.innerHTML = list.map(a=>'<tr class="clickable" data-au="'+AUDIT.indexOf(a)+'"><td class="dim">'+a.t+'</td><td>'+(a.ai?'<span class="rolemark ai">×Agent</span>':'')+a.a+'</td><td>'+a.e+'</td><td class="mono dim">'+a.r+'</td><td>'+(a.ai?'<button class="btn sm" data-au-snap="'+AUDIT.indexOf(a)+'">快照</button>':'—')+'</td></tr>').join('');
  const cnt = $('#auCount'); if (cnt) cnt.textContent = list.length;
  $$('[data-au]').forEach(tr=>tr.onclick=()=>{ const a=AUDIT[tr.dataset.au]; confirmBox('审计详情','<b>'+a.e+'</b><br>操作者：'+a.a+(a.ai?'（用户 × Agent）':'')+'<br>资源：<span class="mono">'+a.r+'</span><br>时间：'+a.t+'<br>来源 IP：10.8.12.30<br>结果：成功',{okText:'关闭'}); });
  $$('[data-au-snap]').forEach(b=>b.onclick=e=>{ e.stopPropagation(); toast('AI 操作快照：能力点=AI诊断 · 输入=构建#127 日志 68 行 · 无写操作 · 审计链完整'); });
}

const LOG_AUTH = [
'Running on witty-agents-ci-runtime:oe2403sp4-node20-py311 (aarch64 / native node)',
'git config --global --add safe.directory /var/jenkins/workspace/witty-agent-package-ci',
'node -e Node.js v20.11.1 detected, requirement satisfied',
'──── stage Initialize Parameters ────',
'AGENT=shennong-crash VARIANT=all PACKAGE_STYLE=organization TARGET_ARCH=aarch64',
'PUBLISH=false NPM_DIST_TAG=latest RUN_REAL_INSTALL_VALIDATION=true',
'rm -rf ci-artifacts && mkdir -p ci-artifacts',
'──── stage Resolve Build Plan ────',
'node ci/scripts/resolve-plan.mjs --agent=shennong-crash --variant=all --package-style=organization --target-arch=aarch64',
'plan resolved: agent=shennong-crash variants=online,offline publish=false',
'wrote ci-artifacts/build-plan.json',
'──── stage Prepare Agents ────',
'loading shennong-crash-agent/ci/agent.json',
'agent shennong-crash registered, changedPathPrefixes: shennong-crash-agent/',
'──── stage Prepare Assets ────',
'GIT_LFS_SKIP_SMUDGE=1 git lfs pull --include=ocr-models',
'OCR model cache hit: /home/witty-agents-jenkins/ocr-model-cache',
'assets prepared for 2 variants (online, offline)',
'──── stage Install Build Dependencies ────',
'npm ci --omit=dev',
'added 214 packages in 41s',
'pip install -i https://mirrors.huaweicloud.com/repository/pypi/simple pyyaml',
'──── stage Validate Agents ────',
'validate shennong-crash: SKILL.md frontmatter ok',
'validate shennong-crash: ci/agent.json schema ok (schemaVersion=1)',
'PASS agent validation for shennong-crash',
'──── stage Build Packages ────',
'building online package @openeuler/witty-agent-shennong@0.10.5-ci.aarch64.0',
'building offline package witty-agent-shennong-offline-0.10.5-ci.aarch64.0',
'packing wheels for offline: /root/.cache/pip/wheels',
'PASS build online artifact 4.2MB',
'PASS build offline artifact 386MB',
'──── stage Artifact Gates ────',
'gate: online-package-report.json exists PASS',
'gate: dist-tag policy check, expected arm-test, found latest in report WARN dist-tag will be overridden by publish stage policy',
'gate: registry candidate generated from gated online artifact',
'registry candidate sha256: 497783c6d7c4c308762134828c2102c4b67497a7e9a20041b82d7471231ed997',
'redownload package from https://registry.npmjs.org/@openeuler/witty-agent-shennong',
'redownloaded sha256: 497783c6d7c4c308762134828c2102c4b67497a7e9a20041b82d7471231ed997',
'PASS sha256 match for candidate 497783c6 (online)',
'ERROR offline wheel integrity check failed: sha256 mismatch',
'expected 7ee96df3937e2b42e212cac1e4cdf66677c2f5009f82a34be31864ba2039bab7',
'found    e5da9462887a330dfc1a7b76d76369ab85873032e5a049c8b887916522704f37',
'possible cause: wheel rebuilt mid-archive, bit flip or partial download from pypi mirror',
'ERROR Artifact Gates failed, downstream stages skipped',
'pipeline aborted at stage Artifact Gates after 41s',
'archiving artifacts: ci-artifacts/**, **/artifacts/**, **/ci-reports/*.json',
'build result: FAILURE'
];
function buildLogLines(){
  const lines = [];
  LOG_AUTH.forEach(l=>lines.push(l));
  return lines;
}
let logRaw = [], logFollow = true, logTimer = null;
const AGENT_IDS_RE = 'shennong-crash|nl2sql|openeuler-ops|xlite-perf-optimizer';
function hlLine(text, q){
  const holds = [];
  const put = html => { holds.push(html); return '\u0001' + (holds.length-1) + '\u0001'; };
  let t = esc(text);
  if (q){ try { t = t.replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'), m=>put('<span class="hit">'+m+'</span>')); } catch(e){} }
  t = t.replace(/https?:\/\/[^\s]+/g, m=>put('<span class="u" data-url="'+m+'">'+m+'</span>'));
  t = t.replace(/\b[0-9a-f]{64}\b/gi, m=>put('<span class="c-sha" title="SHA-256 · '+m.slice(0,8)+'…'+m.slice(-8)+'">'+m.slice(0,10)+'…'+m.slice(-6)+'</span>'));
  t = t.replace(/\b\d+\.\d+\.\d+-ci\.(?:aarch64|x86-64)\.\d+\b/g, m=>put('<span class="c-ver">'+m+'</span>'));
  t = t.replace(/\b(x86-test|arm-test)\b/g, m=>put('<span class="c-tag">'+m+'</span>'));
  t = t.replace(/\blatest\b/g, m=>put('<span class="c-latest">'+m+'</span>'));
  t = t.replace(/(@openeuler\/[A-Za-z0-9._-]+|witty-agent-[A-Za-z0-9._-]+)/g, m=>put('<span class="c-pkg">'+m+'</span>'));
  t = t.replace(new RegExp('\\b('+AGENT_IDS_RE+')\\b','g'), m=>put('<span class="c-ag">'+m+'</span>'));
  t = t.replace(/\b[0-9a-f]{7}\b/g, m=>put('<span class="c-cmt">'+m+'</span>'));
  t = t.replace(/\d{2}:\d{2}:\d{2}/g, m=>put('<span class="ts">'+m+'</span>'));
  t = t.replace(/\u0001(\d+)\u0001/g, (m,i)=>holds[i]);
  return t;
}
function lineClass(t){
  if (t.indexOf('──── stage')===0) return 'sep';
  if (/ERROR|FAILED|FAILURE|exit code 1/i.test(t)) return 'e';
  if (/WARN/.test(t)) return 'w';
  return '';
}
function renderLog(q){
  const view = $('#logView');
  let h = '';
  logRaw.forEach((t,i)=>{
    const cls = lineClass(t);
    let inner = hlLine(t, q);
    if (cls==='' && /PASS|\bOK\b|SUCCESS/.test(t)) inner = inner.replace(/(PASS|OK|SUCCESS)/g,'<span class="okword">$1</span>');
    h += '<div class="ln '+cls+'" data-i="'+i+'"><span class="no">'+(i+1)+'</span><span class="txt">'+inner+'</span></div>';
  });
  view.innerHTML = h;
  const errs = $$('#logView .ln.e').length;
  $('#errCount').textContent = errs;
}
function logErrorNav(dir){
  const view = $('#logView');
  const errs = $$('#logView .ln.e');
  if (!errs.length){ toast('日志中没有错误行','w'); return; }
  let idx = errs.findIndex(el=>el.classList.contains('flash'));
  $$('#logView .ln.flash').forEach(e=>e.classList.remove('flash'));
  let next;
  if (idx===-1) next = dir>0 ? errs[0] : errs[errs.length-1];
  else next = errs[(idx+dir+errs.length)%errs.length];
  next.classList.add('flash');
  view.scrollTop += next.getBoundingClientRect().top - view.getBoundingClientRect().top - view.clientHeight/2 + next.clientHeight/2;
}
function appendLogLine(t){
  logRaw.push(t);
  const view = $('#logView');
  const cls = lineClass(t);
  const div = document.createElement('div');
  div.className = 'ln '+cls;
  div.innerHTML = '<span class="no">'+logRaw.length+'</span><span class="txt">'+hlLine(t)+'</span>';
  view.appendChild(div);
  if (logFollow) view.scrollTop = view.scrollHeight;
}
const SIM_POOL = [
  'npm warn deprecated request@2.88.2',
  'PASS unit check suite (128 cases)',
  'resolving dependency graph for offline wheels',
  'registry poll: https://registry.npmjs.org/@openeuler/witty-agent-shennong visible',
  'downloading 4.2MB from registry',
  'PASS checksum step 3/7',
  'WARN disk usage 82% on /var/jenkins',
  'install → setup → configure → remove → stop → uninstall flow simulated'
];
function initBuildDetail(){
  logRaw = buildLogLines();
  renderLog();
  const view = $('#logView');
  view.onscroll = ()=>{ logFollow = view.scrollHeight-view.scrollTop-view.clientHeight < 48; $('#followChk').checked = logFollow; };
  view.onclick = e=>{ if (e.target.classList.contains('no')){ const ln=e.target.parentElement; const txt=ln.querySelector('.txt').textContent; navigator.clipboard && navigator.clipboard.writeText(txt); toast('已复制第 '+e.target.textContent+' 行日志'); } if (e.target.classList.contains('u')) window.open(e.target.dataset.url,'_blank'); };
  $('#errUp').onclick = ()=>logErrorNav(-1);
  $('#errDown').onclick = ()=>logErrorNav(1);
  $('#logBottom').onclick = ()=>{ view.scrollTop = view.scrollHeight; logFollow = true; $('#followChk').checked = true; };
  $('#followChk').onchange = e=>{ logFollow = e.target.checked; if(logFollow) view.scrollTop=view.scrollHeight; };
  $('#logSearch').addEventListener('keydown', e=>{ if(e.key==='Enter'){ const q=e.target.value.trim(); renderLog(q); const first=$('#logView .hit'); if(first){ view.scrollTop += first.getBoundingClientRect().top - view.getBoundingClientRect().top - view.clientHeight/2; toast('命中 '+$$('#logView .hit').length+' 处「'+q+'」，高亮显示'); } else if(q){ toast('未找到「'+q+'」','w'); } } });
  $('#simBtn').onclick = ()=>{
    if (logTimer){ clearInterval(logTimer); logTimer=null; $('#simBtn').classList.remove('on'); $('#simBtn').textContent='模拟追加'; return; }
    $('#simBtn').classList.add('on'); $('#simBtn').textContent='停止追加';
    logTimer = setInterval(()=>appendLogLine(SIM_POOL[Math.floor(Math.random()*SIM_POOL.length)]), 1200);
    toast('开始模拟实时日志追加，观察自动跟随（滚离底部即暂停跟随）');
  };
  const stagesBox = $('#stageList');
  stagesBox.innerHTML = STAGES.map(s=>{
    const icon = s.st==='done'?'✔':s.st==='fail'?'✖':s.st==='skip'?'○':'●';
    return '<div class="stage-item '+s.st+'" data-stage="'+s.id+'"><span class="st-i">'+icon+'</span>'+s.n+'<span class="st-du">'+s.d+'</span></div>';
  }).join('');
  const stepsBox = $('#stepFlow');
  stepsBox.innerHTML = STAGES.map(s=>'<div class="step clickable '+s.st+'" data-stage="'+s.id+'"><div class="dot">'+(s.st==='done'?'✔':s.st==='fail'?'✖':'')+'</div><div class="nm">'+s.n+'</div><div class="du">'+s.d+'</div></div>').join('');
  const setActiveStage = (id, centerStep)=>{
    $$('.stage-item').forEach(el=>el.classList.toggle('active', el.dataset.stage===id));
    $$('.step').forEach(el=>el.classList.toggle('viewing', el.dataset.stage===id));
    if (centerStep){
      const st = $('.step.viewing'), bar = $('#stepFlow');
      if (st && bar){
        const br = bar.getBoundingClientRect(), sr = st.getBoundingClientRect();
        bar.scrollLeft += sr.left - br.left - (br.width - sr.width)/2;
      }
    }
  };
  const jump = id=>{
    const name = STAGES.find(s=>s.id===id).n;
    const target = $$('#logView .ln.sep').find(el=>el.textContent.includes(name));
    if (target){
      view.scrollTop += target.getBoundingClientRect().top - view.getBoundingClientRect().top - (view.clientHeight - target.clientHeight)/2;
      $$('#logView .ln.flash').forEach(e=>e.classList.remove('flash'));
      target.classList.add('flash');
    }
    setActiveStage(id, true);
  };
  $$('[data-stage]').forEach(el=>el.onclick=()=>{
    const st = STAGES.find(s=>s.id===el.dataset.stage);
    if (st && st.st==='skip'){ toast('「'+st.n+'」为条件阶段，本轮未执行（前置 Artifact Gates 失败后跳过），无对应日志','w'); return; }
    jump(el.dataset.stage);
  });
  setActiveStage('gates', false);
  let spy = false;
  view.addEventListener('scroll', ()=>{
    if (spy) return; spy = true;
    raf(()=>{
      spy = false;
      const seps = $$('#logView .ln.sep');
      if (!seps.length) return;
      const vtop = view.getBoundingClientRect().top;
      let cur = 0;
      seps.forEach((el,i)=>{ if (el.getBoundingClientRect().top - vtop < 8) cur = i; });
      const id = STAGES[cur] && STAGES[cur].id;
      if (id && !$('.stage-item.active[data-stage="'+id+'"]')) setActiveStage(id, false);
    });
  });
  $('#aiToggle').onclick = ()=>{
    const p = $('#aiDiag');
    if (!p.classList.contains('hidden')){ p.classList.add('hidden'); return; }
    aiLoad('aiDiag','aiDiagBody',
      aiMetrics([{k:'失败阶段',v:'Artifact Gates',t:'bad'},{k:'错误行',v:'3 处',t:'bad'},{k:'online 变体',v:'通过',t:'good'},{k:'影响面',v:'offline 产物'}])+
      '<div class="ai-sec">根因判定</div><div class="ai-body">offline wheel 完整性校验失败：归档包与重打包 wheel 的 <b>SHA-256 不一致</b>，差异集中在哈希末段——符合「镜像源回源后 wheel 被重建」特征；历史相似案例 4 例，3 例同因。</div>'+
      '<div class="ai-sec">证据链</div>'+
      '<div class="ai-ev"><i>错误 1/3</i><span>ERROR offline wheel integrity check failed: sha256 mismatch · <span class="lnk" id="aiJump">跳转日志行</span></span></div>'+
      '<div class="ai-ev"><i>哈希</i><span>expected <span class="mono">7ee96df3…9bab7</span> ≠ found <span class="mono">e5da9462…4f37</span>（末段漂移）</span></div>'+
      '<div class="ai-ev"><i>阶段</i><span>Prepare → Gates 间隔 2m33s，期间源码零变更（commit a1b2c3d 未动）· <span class="lnk" id="aiStage">定位失败阶段</span></span></div>'+
      '<div class="ai-sec">建议动作</div>'+
      '<div class="ai-sug"><span class="n">1</span>以 online 变体先行发布验证链路（不受 wheel 打包影响），可一键按推荐参数重跑</div>'+
      '<div class="ai-sug"><span class="n">2</span>切换 PYPI_INDEX_URL 至内网镜像——项目设置已有 AI 建议 diff（高危，需人审）</div>'+
      '<div class="ai-sug"><span class="n">3</span>重跑前清理 Jenkins 节点 pip 缓存目录，避免复用坏 wheel</div>'+
      aiConf(78,'基于 68 行日志 + 4 例历史案例')+
      '<div class="ai-actions"><button class="btn sm primary" id="aiRerun">按推荐参数重跑（online / aarch64）</button><button class="btn sm" data-go="builds.html">返回列表</button><span class="ai-fb">诊断质量：<span>👍</span><span>👎</span></span></div>',
      ()=>{
        $('#aiJump').onclick = ()=>logErrorNav(1);
        $('#aiRerun').onclick = ()=>openTriggerDrawer({agent:'shennong-crash',variant:'online',style:'plain',arch:'aarch64',showAi:true});
        $('#aiStage').onclick = ()=>{
          const bar = $('#stepFlow');
          window.scrollTo({ top: bar.getBoundingClientRect().top + window.scrollY - 76, behavior:'smooth' });
          toast('已定位到失败阶段：Artifact Gates');
        };
        $$('#aiDiag .ai-fb span').forEach(s=>s.onclick=()=>toast('感谢反馈，用于优化诊断模型（mock）'));
      },
      'AI 分析中：读取 68 行日志 → 提取错误上下文 → 关联阶段时序 → 匹配已知失败模式…');
  };
  $('#aiClose').onclick = ()=>$('#aiDiag').classList.add('hidden');
  $('#cancelBtn').onclick = ()=>toast('构建已结束，无法取消','w');
  $('#replayBtn').onclick = ()=>confirmBox('Replay 失败阶段','将基于构建 <b class="mono">#127</b> 的 Jenkins Replay 重跑失败阶段（Artifact Gates 起）。',{okText:'Replay',onOk:()=>toast('已发起 Replay（mock：新构建 #129，从 Artifact Gates 开始）','s')});
  $('#dlLog').onclick = ()=>toast('正在下载全量日志 build-127.log（mock）','s');
  $$('[data-dl-art]').forEach(b=>b.onclick=()=>toast('开始下载 '+b.dataset.dlArt+'（mock）','s'));
}

document.addEventListener('DOMContentLoaded', ()=>{
  navShell();
  const page = document.body.dataset.page;
  if (page==='builds'){
    $('#bFilterAgent').innerHTML = '<option value="all">全部范围</option><option value="auto">增量（auto）</option>'+AGENTS.map(a=>'<option value="'+a.id+'">'+a.id+'</option>').join('');
    ['bFilterStatus','bFilterAgent','bFilterBy','bDateFrom','bDateTo'].forEach(id=>$('#'+id).onchange=()=>{ $('#bPage').dataset.cur=1; renderBuildsTable(); });
    $('#bTrigger').onclick = ()=>openTriggerDrawer();
    $('#bExport').onclick = ()=>{
      const d1 = $('#bDateFrom').value, d2 = $('#bDateTo').value;
      if (!d1 || !d2){ toast('请先选择导出的起止日期','w'); return; }
      const n = filteredBuilds().length;
      confirmBox('导出构建记录',
        '时间范围：<b>'+fmtCN(d1)+' 至 '+fmtCN(d2)+'</b>（叠加当前筛选条件）<br>预计导出 <b class="mono">'+n+'</b> 条记录 · CSV 字段：编号 / Agent / 参数 / 触发人 / 状态 / 耗时 / 日期',
        {okText:'导出 CSV', onOk:()=>toast('已导出 '+fmtCN(d1)+' 至 '+fmtCN(d2)+' 的 '+n+' 条构建记录（mock：builds-export.csv）','s')});
    };
    $('#aiSumBtn').onclick = ()=>aiLoad('aiSummary','aiSumBody',
      aiMetrics([{k:'失败率',v:'25%',t:'bad'},{k:'失败集中阶段',v:'Artifact Gates',t:'bad'},{k:'online 通过率',v:'100%',t:'good'},{k:'自动构建占比',v:'61%'}])+
      '<div class="ai-sec">结论</div><div class="ai-body">5/20 次失败全部位于 <b>Artifact Gates</b>，根因均为 offline wheel 的 SHA-256 不一致；Top 失败 Agent：shennong-crash（3 次）、auto 增量（2 次，均命中间接依赖）。成功构建中 online 变体通过率 100%。</div>'+
      '<div class="ai-sec">建议</div>'+
      '<div class="ai-sug"><span class="n">1</span>以 VARIANT=online 触发构建并走发布链路，先恢复交付节奏</div>'+
      '<div class="ai-sug"><span class="n">2</span>推进 pypi 镜像治理——项目设置已有 AI 建议 diff（高危，需人审）</div>'+
      aiConf(86,'基于近 20 次构建 × 5 维特征')+
      '<div class="ai-actions"><button class="btn sm primary" onclick="openTriggerDrawer({variant:\'online\'})">按建议触发构建</button><button class="btn sm" data-go="build-detail.html">查看 #127 诊断</button><span class="ai-fb">这条汇总：<span>👍 有用</span><span>👎 无用</span></span></div>',
      null, 'AI 汇总中：聚合近 20 次构建 → 提取失败特征 → 归因排序…');
    $('#aiSumClose').onclick = ()=>$('#aiSummary').classList.add('hidden');
    renderBuildsTable();
  }
  if (page==='build-detail'){ initBuildDetail(); $('#retrigger').onclick=()=>openTriggerDrawer(); }
  if (page==='agents'){
    $('#aSearch').oninput = renderAgents;
    $('#aFilterStatus').onchange = renderAgents;
    renderAgents();
  }
  if (page==='users'){
    $('#uAdd').onclick = ()=>confirmBox('添加用户',
      '<div class="form-grid"><div class="fi"><label>用户名 <i>*</i></label><input class="inp" id="nuU"></div>'+
      '<div class="fi"><label>姓名</label><input class="inp" id="nuN"></div>'+
      '<div class="fi full"><label>系统角色</label><select class="inp" id="nuR"><option>项目管理员</option><option>开发成员</option><option>只读访客</option><option>系统管理员</option></select></div></div>',
      {okText:'创建', onOk:()=>{ const u=$('#nuU').value||'newuser'; USERS.unshift({u, n:$('#nuN').value||u, r:$('#nuR').value, on:true, t:'刚刚'}); renderUsers(); toast('用户 '+u+' 已创建，初始密码已邮件发送（mock）','s'); }});
    renderUsers();
  }
  if (page==='audit'){
    $('#auFilterEv').onchange = renderAudit;
    $('#auOnlyAi').onchange = renderAudit;
    $('#auSearch').oninput = renderAudit;
    $('#auExport').onclick = ()=>toast('审计导出仅系统管理员可用（mock：已生成 CSV）','s');
    renderAudit();
  }
  if (page==='release'){
    $('#gateExplain').onclick = ()=>confirmBox('AI 解释与修复建议 · SHA-256 不一致',
      '<div class="ai-sec" style="margin-top:0">诱因概率分布</div>'+
      '<div class="ai-prob"><span class="mono">①</span><div><div>registry 镜像同步延迟 <span class="dim">——发布 3s 后即回下载，命中旧缓存层</span></div><div class="track"><span class="fill" style="display:block;width:78%"></span></div></div><span class="pct">78%</span></div>'+
      '<div class="ai-prob"><span class="mono">②</span><div><div>包名改写 metadata 时序 <span class="dim">——@openeuler/* 转 witty-agent-shennong</span></div><div class="track"><span class="fill" style="display:block;width:15%"></span></div></div><span class="pct">15%</span></div>'+
      '<div class="ai-prob"><span class="mono">③</span><div><div>registry 侧覆盖写入</div><div class="track"><span class="fill" style="display:block;width:7%"></span></div></div><span class="pct">7%</span></div>'+
      '<div class="ai-sec">建议</div>'+
      '<div class="ai-sug"><span class="n">1</span>5 分钟后重新执行回下载核验（低危，AI 可代执行）</div>'+
      '<div class="ai-sug"><span class="n">2</span>若仍不一致：冻结该版本，联系 registry 值班并保留双端哈希证据</div>'+
      '<div class="hint" style="margin-top:10px">护栏：重新核验属读取类低危操作，AI 可代执行；dist-tag 变更/回滚属发布类，AI 仅建议不代执行。</div>',
      {okText:'让 AI 5 分钟后重试核验', onOk:()=>toast('AI 低危代执行：已登记 5 分钟后重试回下载核验，结果将通知（mock）','s')});
    $('#rbBtn').onclick = ()=>confirmBox('回滚 dist-tag','将 <span class="mono">witty-agent-shennong</span> 的 <span class="mono">arm-test</span> 从 <b>0.10.5-ci.aarch64.0</b> 切回上一指向 <b>0.10.4-ci.aarch64.3</b>。<br><br><div class="hint">AI 助手在此场景仅提供建议，不代执行回滚（发布类护栏）。</div>',{danger:true, okText:'执行回滚', onOk:()=>toast('dist-tag arm-test 已切回 0.10.4-ci.aarch64.3，事件已通知并写入审计','s')});
    $('#aiRiskBtn').onclick = ()=>aiLoad('aiRisk','aiRiskBody',
      aiMetrics([{k:'arm-test 可用率',v:'92%',t:'good'},{k:'镜像延迟 P95',v:'40s'},{k:'本次判定',v:'镜像缓存',t:'bad'},{k:'latest 影响',v:'无',t:'good'}])+
      '<div class="ai-sec">结论</div><div class="ai-body">本包近 3 次发布 1 次 SHA-256 待核查（本次）。registry 华东镜像同步延迟 P95 ≈ 40s，与本次「发布后 3s 即回下载」窗口重叠——<b>约 78% 概率为镜像缓存问题，重试核验即可通过</b>。</div>'+
      '<div class="ai-sec">建议</div>'+
      '<div class="ai-sug"><span class="n">1</span>登记 5 分钟后重试核验（低危，可代执行）</div>'+
      '<div class="ai-sug"><span class="n">2</span>arm-test 暂缓被下游依赖，latest 保持 0.10.3 不动</div>'+
      aiConf(78,'结合 30 天发布链路遥测')+
      '<div class="ai-actions"><button class="btn sm primary" data-toast="AI 低危代执行：已登记 5 分钟后重试回下载核验（mock）">登记重试核验</button><button class="btn sm" id="goPublish">查看发布流程要求</button><span class="ai-fb">这条摘要：<span>👍 有用</span><span>👎 无用</span></span></div>',
      ()=>{ $('#goPublish').onclick = ()=>toast('发布类操作 AI 不代执行：请从「构建流水线」选择已通过门禁的构建发起发布（REL-01）','w'); },
      'AI 评估中：拉取发布链路遥测 → 对齐镜像延迟窗口 → 计算判定分布…');
    $('#aiRiskClose').onclick = ()=>$('#aiRisk').classList.add('hidden');
  }
  if (page==='overview'){
    renderHealthTable();
    $('#ovAgents').textContent = String(AGENTS.length);
    $('#ovAgentsFoot').textContent = 'enabled ' + AGENTS.filter(a=>a.en).length + ' · schemaVersion=1';
    $('#ovBuilds').textContent = String(BUILDS.length);
    $('#ovRate').textContent = Math.round(BUILDS.filter(b=>b.status==='s').length / BUILDS.length * 100) + '%';
    bindRowFilter('agfQ', [{key:'en', id:'agfEn'}, {key:'last', id:'agfLast'}], '[data-ag-row]', 'agfCount');
    bindRowFilter('mbfQ', [{key:'role', id:'mbfRole'}], '[data-mb-row]', 'mbfCount');
    $$('[data-conn]').forEach(b=>b.onclick=()=>{ const old=b.textContent; b.textContent='检测中…'; b.disabled=true; setTimeout(()=>{ b.textContent=old; b.disabled=false; toast('连通性正常（mock）：RTT 42ms','s'); },700); });
    $('#aiCfgBtn').onclick = ()=>{ $('#aiCfgCard').classList.toggle('hidden'); };
    $('#aiCfgApply').onclick = ()=>{ $('#aiCfgCard').classList.add('hidden'); toast('配置变更已应用（高危·人审通过），已写入审计：张伟 × Agent','s'); };
    $('#aiCfgDrop').onclick = ()=>{ $('#aiCfgCard').classList.add('hidden'); toast('已放弃 AI 建议，未产生任何变更','w'); };
    $('#aiCfgRefresh').onclick = ()=>toast('已基于最新配置重新生成建议（mock）');
  }
  if (page==='dashboard'){
    const st = agentStats();
    $('#stAgents').textContent = AGENTS.filter(a=>a.en).length + ' / ' + AGENTS.length;
    $('#stBuilds').textContent = String(BUILDS.length);
    $('#stRate').textContent = Math.round(BUILDS.filter(b=>b.status==='s').length / BUILDS.length * 100) + '%';
    $('#recentBuilds').innerHTML = BUILDS.slice(0,5).map(b=>
      '<tr class="clickable" data-go="'+(b.no===127?'build-detail.html':'builds.html')+'"><td class="link mono">#'+b.no+'</td><td class="mono">'+b.agent+'</td><td>'+b.by+'</td><td>'+statusTag(b.status)+'</td><td class="mono">'+b.dur+'</td><td class="dim">'+b.time+'</td></tr>').join('');
    const chartSel = new Set(AGENTS.map(a=>a.id));
    let chartTop = '5';
    const cfBtn = $('#cfBtn');
    $('#cfList').innerHTML = AGENTS.map(a=>'<label class="cf-row" data-name="'+a.id+' '+a.name+'"><input type="checkbox" value="'+a.id+'" checked><span>'+a.name+' <span class="dim mono">'+a.id+'</span></span><span class="cnt">构建 '+st[a.id].b+' · 下载 '+st[a.id].dl+'</span></label>').join('');
    const renderCharts = ()=>{
      const s2 = agentStats();
      const sel = AGENTS.filter(a=>chartSel.has(a.id) && (s2[a.id].b>0 || s2[a.id].dl>0))
        .sort((x,y)=>s2[y.id].b - s2[x.id].b);
      const N = chartTop==='all' ? sel.length : Math.min(parseInt(chartTop), sel.length);
      const shown = sel.slice(0, N), rest = sel.slice(N);
      const items = shown.map((a,i)=>({id:a.id, name:a.name, b:s2[a.id].b, dl:s2[a.id].dl, color:PIE_COLORS[i%PIE_COLORS.length]}));
      if (rest.length){
        items.push({id:'__other', name:'其他（'+rest.length+' 个）', b:rest.reduce((s,a)=>s+s2[a.id].b,0), dl:rest.reduce((s,a)=>s+s2[a.id].dl,0), color:'#cdd6e0'});
      }
      cfBtn.textContent = '筛选 Agent（'+sel.length+'）▾';
      const donut = $('#donut');
      const tot = items.reduce((s,x)=>s+x.b, 0);
      if (!items.length){
        donut.style.background = '#f0f3f7';
        donut.innerHTML = '<div class="center"><b>—</b><span>未选择</span></div>';
        $('#pieLegend').innerHTML = '<div class="lg dim">未选择任何 Agent，勾选筛选器以展示统计</div>';
        $('#agentBars').innerHTML = '<div class="dim" style="padding:40px 0">未选择任何 Agent</div>';
        return;
      }
      let acc = 0; const segs = [];
      items.forEach(x=>{ if (!x.b) return; const from = acc/tot*360; acc += x.b; segs.push(x.color+' '+from.toFixed(1)+'deg '+(acc/tot*360).toFixed(1)+'deg'); });
      donut.style.background = segs.length ? 'conic-gradient('+segs.join(',')+')' : '#f0f3f7';
      donut.innerHTML = '<div class="center"><b>'+tot+'</b><span>次构建</span></div>';
      const LEGEND_K = 6;
      const lgRow = x=>'<div class="lg" title="'+x.id+'"><i style="background:'+x.color+'"></i>'+x.name+'<b>'+(x.b?' '+x.b+' 次 · '+Math.round(x.b/tot*100)+'%':' 无构建')+'</b></div>';
      const allRows = items.map(lgRow).join('');
      let lgHtml = items.slice(0, LEGEND_K).map(lgRow).join('');
      if (items.length > LEGEND_K){
        lgHtml += '<span class="lg-more">… 其余 <b>'+(items.length-LEGEND_K)+'</b> 项<span class="lg-pop"><div class="p-title">全部 '+items.length+' 项（构建 / 占比）</div>'+allRows+'</span></span>';
      }
      $('#pieLegend').innerHTML = lgHtml;
      const maxB = Math.max(...items.map(x=>x.b)) || 1, maxD = Math.max(...items.map(x=>x.dl)) || 1;
      $('#agentBars').innerHTML = items.map(x=>
        '<div class="bar-g" title="'+x.id+'"><div class="pair">'+
        '<div class="vbar build" style="height:'+(x.b?Math.max(7,x.b/maxB*100).toFixed(0):2)+'%"><span class="val">'+x.b+'</span></div>'+
        '<div class="vbar dl" style="height:'+(x.dl?Math.max(7,x.dl/maxD*100).toFixed(0):2)+'%"><span class="val">'+x.dl+'</span></div>'+
        '</div><div class="xlab">'+x.name+'</div></div>').join('');
    };
    cfBtn.onclick = e=>{ e.stopPropagation(); $('#cfDd').classList.toggle('show'); };
    $('#cfDd').onclick = e=>e.stopPropagation();
    $('#cfSearch').oninput = e=>{
      const q = e.target.value.trim().toLowerCase();
      let shown = 0;
      $$('#cfList .cf-row').forEach(r=>{
        const ok = !q || (r.dataset.name || '').toLowerCase().includes(q);
        r.style.display = ok ? '' : 'none';
        if (ok) shown++;
      });
      $('#cfEmpty').style.display = shown ? 'none' : '';
    };
    $('#cfList').addEventListener('change', e=>{
      if (e.target.matches('input[type="checkbox"]')){
        e.target.checked ? chartSel.add(e.target.value) : chartSel.delete(e.target.value);
        renderCharts();
      }
    });
    $('#cfAll').onclick = ()=>{ chartSel.clear(); AGENTS.forEach(a=>chartSel.add(a.id)); $$('#cfList input').forEach(i=>i.checked=true); renderCharts(); };
    $('#cfNone').onclick = ()=>{ chartSel.clear(); $$('#cfList input').forEach(i=>i.checked=false); renderCharts(); };
    $('#cfTop').onchange = e=>{ chartTop = e.target.value; renderCharts(); };
    renderCharts();
    $('#aiTrendBtn').onclick = ()=>aiLoad('aiTrend','aiTrendBody',
      aiMetrics([{k:'构建成功率',v:'78%',t:'bad'},{k:'失败集中',v:'Gates 3/4',t:'bad'},{k:'online 变体',v:'7 日全过',t:'good'},{k:'自动构建占比',v:'61%'}])+
      '<div class="ai-sec">结论</div><div class="ai-body">构建量稳定在 3~4 次/天（pollSCM 为主）。失败集中在 <b>Artifact Gates（SHA-256 校验）</b>，占失败的 3/4，全部来自 offline wheel 打包链路；online 变体 7 日内全部通过，可先行承接交付。</div>'+
      '<div class="ai-sec">建议</div>'+
      '<div class="ai-sug"><span class="n">1</span>优先检查 pypi 镜像源一致性（项目设置 → AI 建议已有切换 diff）</div>'+
      '<div class="ai-sug"><span class="n">2</span>短期以 online 变体发布，offline 链路修复后再切回 all</div>'+
      aiConf(84,'基于 7 日 × 23 次构建'),
      null, 'AI 解读中：对齐 7 日构建序列 → 分离变体维度 → 定位失败聚集…');
    $('#aiTrendClose').onclick = ()=>$('#aiTrend').classList.add('hidden');
  }
  if (page==='login'){
    $('#loginBtn').onclick = ()=>{
      const u=$('#lgUser').value, p=$('#lgPass').value;
      if(!u||!p){ toast('请输入用户名和密码','w'); return; }
      const b=$('#loginBtn'); b.textContent='登录中…'; b.disabled=true;
      setTimeout(()=>{ location.href='dashboard.html'; }, 700);
    };
    $('#lgUser').addEventListener('keydown',e=>{ if(e.key==='Enter') $('#lgPass').focus(); });
    $('#lgPass').addEventListener('keydown',e=>{ if(e.key==='Enter') $('#loginBtn').click(); });
  }
});
