// 制造减免规则(组件计算器 / 成本查询共用)
// 数据来源:游戏 SDE,经晨曦 ESI dogma 属性核实(attributeEngRigMatBonus / hiSecModifier / strEngMatBonus)
// 独立的静态文件,避免两个页面各写一份改装件/结构数值而逐渐走样。
(function (global) {
    'use strict';

    // 一座工程综合体最多 3 个改装件槽位;同类改装件不叠加,取最高减免
    // structMe = 材料减免;structFee = 制造安装费减免(只作用于星系成本系数部分)
    const STRUCTURES = [
        { id: 'station', label: 'NPC 站(无任何减免)', size: null, structMe: 0, structFee: 0 },
        { id: 'raitaru', label: '莱塔卢(中型 EC,材料 1%,费用 3%)', size: 'M', structMe: 0.01, structFee: 0.03 },
        { id: 'azbel', label: '阿兹贝尔(大型 EC,材料 1%,费用 4%)', size: 'L', structMe: 0.01, structFee: 0.04 },
        { id: 'sotiyo', label: '索迪约(超大型 EC,材料 1%,费用 5%)', size: 'XL', structMe: 0.01, structFee: 0.05 },
    ];

    // 改装件:base 为基础减免(T1=2.0%, T2=2.4%),scope 为适用的物品分类;size 须与建筑规格匹配
    const RIG_POOL = [
        { id: 'M-adv1', size: 'M', label: '高级组件制造材料效率 I (2.0%)', base: 0.02, scope: ['旗舰高级组件', 'T2制造组件'] },
        { id: 'M-adv2', size: 'M', label: '高级组件制造材料效率 II (2.4%)', base: 0.024, scope: ['旗舰高级组件', 'T2制造组件'] },
        { id: 'M-cap1', size: 'M', label: '基础旗舰组件制造材料效率 I (2.0%)', base: 0.02, scope: ['旗舰基础组件'] },
        { id: 'M-cap2', size: 'M', label: '基础旗舰组件制造材料效率 II (2.4%)', base: 0.024, scope: ['旗舰基础组件'] },
        { id: 'L-adv1', size: 'L', label: '高级组件制造效率 I (2.0%)', base: 0.02, scope: ['旗舰高级组件', 'T2制造组件'] },
        { id: 'L-adv2', size: 'L', label: '高级组件制造效率 II (2.4%)', base: 0.024, scope: ['旗舰高级组件', 'T2制造组件'] },
        { id: 'L-cap1', size: 'L', label: '基础旗舰组件制造效率 I (2.0%)', base: 0.02, scope: ['旗舰基础组件'] },
        { id: 'L-cap2', size: 'L', label: '基础旗舰组件制造效率 II (2.4%)', base: 0.024, scope: ['旗舰基础组件'] },
        { id: 'XL-1', size: 'XL', label: '建筑和组件制造效率 I (2.0%)', base: 0.02, scope: ['旗舰基础组件', '旗舰高级组件', 'T2制造组件'] },
        { id: 'XL-2', size: 'XL', label: '建筑和组件制造效率 II (2.4%)', base: 0.024, scope: ['旗舰基础组件', '旗舰高级组件', 'T2制造组件'] },
    ];

    const MAX_RIG_SLOTS = 3;

    // 安等系数:改装件效果按星系类别放大 —— 高安 ×1.0 / 低安 ×1.9 / 00 与虫洞 ×2.1
    // 只放大改装件,不放大结构固有 1%
    const SEC_PRESETS = [
        { id: 'hisec', label: '高安 (0.5 ~ 1.0) — 改装件系数 ×1.0', scale: 1.0 },
        { id: 'lowsec', label: '低安 (0.1 ~ 0.4) — 改装件系数 ×1.9', scale: 1.9 },
        { id: 'nullsec', label: '00 / 虫洞 (-0.0 ~ -1.0) — 改装件系数 ×2.1', scale: 2.1 },
    ];

    // 同类改装件不叠加:对指定分类取所有已装适用改装件中的最高基础减免,再乘安等系数
    function rigBonusFor(tier, rigs, scale) {
        let best = 0;
        (rigs || []).forEach(function (r) {
            if (r.scope.indexOf(tier) !== -1) best = Math.max(best, r.base);
        });
        return best * (scale || 1);
    }

    // 蓝图 ME:每级 −1%,0~10 级
    function meFactor(meLevel) {
        const me = Math.max(0, Math.min(10, Number(meLevel) || 0));
        return 1 - 0.01 * me;
    }

    // 安装费费率 = 星系成本系数 × (1 − 建筑费用减免) + SCC 附加费 4%
    function feeRate(sciPercent, structFee) {
        const sci = Math.max(0, Number(sciPercent) || 0) / 100;
        return sci * (1 - (structFee || 0)) + 0.04;
    }

    global.CRAFT_RULES = {
        STRUCTURES: STRUCTURES,
        RIG_POOL: RIG_POOL,
        SEC_PRESETS: SEC_PRESETS,
        MAX_RIG_SLOTS: MAX_RIG_SLOTS,
        rigBonusFor: rigBonusFor,
        meFactor: meFactor,
        feeRate: feeRate,
    };
})(window);
