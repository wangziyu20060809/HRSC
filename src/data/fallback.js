/* 内嵌兜底数据：通过 file:// 直接打开时 fetch 会被浏览器拦截，这里内联一份同样的内容。
   修改 data/*.json 后请重新生成此文件。 */
window.FDE_FALLBACK = {
  "project": {
    "projectId": "travel-hotel",
    "company": "山海旅居",
    "name": "酒店房态与入住协同",
    "summary": "围绕「已清扫 / 已查房 / 可售」三态时序脱节，建立三态一致的房态协同与人工复核闭环。",
    "roles": [
      {
        "id": "travel-hotel-r0",
        "name": "顾明岚",
        "role": "酒店运营经理",
        "kind": "共同提出人",
        "concern": "指标与预算，收益须扣除维护与复核成本"
      },
      {
        "id": "travel-hotel-r1",
        "name": "林亦舟",
        "role": "前台接待员",
        "kind": "主问题提出人",
        "concern": "高峰只能用现有终端，不能离场补录"
      },
      {
        "id": "travel-hotel-r2",
        "name": "唐映秋",
        "role": "客房调度员",
        "kind": "流程执行",
        "concern": "排单优先级与清扫排程"
      },
      {
        "id": "travel-hotel-r3",
        "name": "秦芮",
        "role": "PMS 工程师",
        "kind": "技术与权限",
        "concern": "三套系统权限独立、接口只读"
      },
      {
        "id": "travel-hotel-r4",
        "name": "傅景",
        "role": "服务质量专员",
        "kind": "风险否决",
        "concern": "可因关键风险否决上线"
      },
      {
        "id": "travel-hotel-r5",
        "name": "叶书",
        "role": "客人体验主管",
        "kind": "体验视角",
        "concern": "等待时长与对外承诺"
      }
    ],
    "facts": [
      {
        "id": "f00",
        "text": "误判定义未统一：仅计状态错配，还是前台据此对外承诺也计入，两种口径验收结论完全不同。",
        "source": "访谈·顾明岚",
        "status": "待核实"
      },
      {
        "id": "f01",
        "text": "等待基线未定：从『查房完成』还是『清扫结束』起算尚未确定。",
        "source": "访谈·顾明岚",
        "status": "待核实"
      },
      {
        "id": "f02",
        "text": "验收要求连续 4 周，遇节假日或大型接待需顺延重跑。",
        "source": "访谈·傅景",
        "status": "已确认"
      },
      {
        "id": "f03",
        "text": "收益须扣除维护及人工复核成本，不能把全部节省工时当作现金回款。",
        "source": "访谈·顾明岚",
        "status": "已确认"
      },
      {
        "id": "f04",
        "text": "服务质量专员可因关键风险否决上线。",
        "source": "访谈·傅景",
        "status": "已确认"
      },
      {
        "id": "f12",
        "text": "高峰时段只能使用现有终端，离开现场补录会延误处理。",
        "source": "访谈·林亦舟",
        "status": "已确认"
      },
      {
        "id": "f13",
        "text": "一线不得离场补录，回写必须一个动作完成。",
        "source": "访谈·林亦舟",
        "status": "已确认"
      },
      {
        "id": "f30",
        "text": "三套系统权限各自独立维护，状态无统一视图。",
        "source": "访谈·秦芮",
        "status": "已确认"
      },
      {
        "id": "f32",
        "text": "现有接口仅可读，不能写回生产库。",
        "source": "访谈·秦芮",
        "status": "已确认"
      },
      {
        "id": "f43",
        "text": "查房照片等证据的存储与 90 天期满清理规则未定。",
        "source": "访谈·傅景",
        "status": "待核实"
      },
      {
        "id": "f44",
        "text": "异常需具名接收人标注原因与确认时间；维修房带预订的处理流程尚未核实。",
        "source": "访谈·傅景",
        "status": "待核实"
      },
      {
        "id": "f45",
        "text": "审计需能重建单次处理，且不记录不必要个人信息。",
        "source": "访谈·傅景",
        "status": "已确认"
      },
      {
        "id": "f53",
        "text": "客房看『清扫结束』、前台看『可交付』、渠道看『可售』，三岗完成时间须分别记录。",
        "source": "访谈·唐映秋",
        "status": "已确认"
      }
    ],
    "metrics": [
      {
        "id": "wait",
        "label": "高峰入住等待",
        "baseline": 38,
        "target": 15,
        "unit": "分钟",
        "owner": "前台",
        "note": "从查房完成到办理入住"
      },
      {
        "id": "error",
        "label": "房态错误",
        "baseline": 24,
        "target": 5,
        "unit": "次/周",
        "owner": "质检",
        "note": "口径需先签字确认"
      },
      {
        "id": "turn",
        "label": "退房到可售周转",
        "baseline": 96,
        "target": 70,
        "unit": "分钟",
        "owner": "客房调度",
        "note": "现状为估计值，需实测"
      },
      {
        "id": "audit",
        "label": "异常具名接收率",
        "baseline": 0,
        "target": 100,
        "unit": "%",
        "owner": "质检",
        "note": "试点后新增指标"
      }
    ],
    "budget": {
      "total": 130000,
      "currency": "CNY",
      "note": "首期含集成、培训与验证；复核成本按月计入运营"
    }
  },
  "stages": {
    "projectId": "travel-hotel",
    "company": "山海旅居",
    "name": "酒店房态与入住协同",
    "sector": "文旅",
    "summary": "围绕客房清扫、查房复核与前台可售状态之间的时序脱节，建立三态一致的房态协同与人工复核闭环。",
    "stages": [
      {
        "id": "opportunity",
        "title": "业务挖掘",
        "goal": "从经营目标、真实事件和指标基线中判断是否值得立项。",
        "gate": "业务负责人确认问题、指标口径与调查范围",
        "steps": [
          {
            "id": "opportunity-trigger",
            "title": "识别业务机会",
            "action": "收集最近一次异常事件，区分客户提出的功能和真正要改善的业务结果。",
            "output": "业务机会清单",
            "question": "哪个具体事件触发了需求？如果维持现状，会产生什么损失？"
          },
          {
            "id": "opportunity-baseline",
            "title": "建立现状基线",
            "action": "定义指标分子、分母、时间窗、样本来源和测量责任人。",
            "output": "指标基线与价值假设",
            "question": "现状耗时、返工和错误如何计算？哪些数字还只是估计？"
          },
          {
            "id": "opportunity-mandate",
            "title": "确认立项与决策链",
            "action": "确认业务发起人、预算归属、否决权人和试点范围。",
            "output": "项目章程与利益相关者地图",
            "question": "谁能否决这个项目？预算由谁签字？"
          }
        ]
      },
      {
        "id": "discovery",
        "title": "现场调研",
        "goal": "还原实际流程，用多角色和多来源材料核实问题。",
        "gate": "关键流程、异常、证据矛盾和待核实项已形成记录",
        "steps": [
          {
            "id": "discovery-interviews",
            "title": "开展角色访谈",
            "action": "按岗位访谈运营、前台、客房调度、PMS 工程师与质检。",
            "output": "访谈记录与角色地图",
            "question": "每个岗位说的『房间好了』指的是哪一个状态？"
          },
          {
            "id": "discovery-process",
            "title": "还原现状流程",
            "action": "画出从退房到入住的真实链路，标出异常路径与口头兜底。",
            "output": "现状流程图与异常路径",
            "question": "哪个环节在系统外靠电话或口头确认？"
          },
          {
            "id": "discovery-evidence",
            "title": "四来源收敛与材料核对",
            "action": "把访谈、系统日志、单据与行业参照对齐，标出矛盾。",
            "output": "四来源收敛表、证据台账与问题清单",
            "question": "哪条结论只有一个来源支撑？"
          }
        ]
      },
      {
        "id": "definition",
        "title": "需求定义",
        "goal": "把调查发现收敛为有证据、可验收、可追责的需求。",
        "gate": "问题优先级、需求范围和可测验收条件均有确认记录",
        "steps": [
          {
            "id": "definition-prioritize",
            "title": "确定优先问题",
            "action": "按影响面、可测性与实施成本排序候选问题。",
            "output": "问题优先级与机会判断",
            "question": "为什么先做这一个，而不是别的三个？"
          },
          {
            "id": "definition-requirements",
            "title": "编写需求与边界",
            "action": "写清需求条目、追溯来源与明确不做的事。",
            "output": "需求规格与追溯矩阵",
            "question": "每条需求能追到哪条事实？"
          },
          {
            "id": "definition-acceptance",
            "title": "约定验收标准",
            "action": "把『误判为零』这类口号拆成可测字段与判定人。",
            "output": "验收清单与需求确认记录",
            "question": "谁来判定这条验收通过？"
          }
        ]
      },
      {
        "id": "solution",
        "title": "方案设计",
        "goal": "把需求约束转化成可实施的系统边界与试点方案。",
        "gate": "试点边界、方案取舍、数据权限与实施计划已评审",
        "steps": [
          {
            "id": "solution-wedge",
            "title": "选定最小试点",
            "action": "确定首个试点范围、时间窗与回退条件。",
            "output": "试点方案与方案比较",
            "question": "试点做哪几栋楼、哪几个班次？"
          },
          {
            "id": "solution-architecture",
            "title": "设计数据和系统边界",
            "action": "确定只读接入、字段映射、权限矩阵与隐私边界。",
            "output": "架构图、数据与权限矩阵",
            "question": "哪些字段必须脱敏？谁能看到？"
          },
          {
            "id": "solution-plan",
            "title": "制定构建与评估计划",
            "action": "排出构建、评估、风险与人力计划。",
            "output": "构建计划、评估计划与风险表",
            "question": "最大的技术风险是什么，怎么提前验？"
          }
        ]
      },
      {
        "id": "build",
        "title": "构建集成",
        "goal": "把方案落成可运行、可复现、可审计的业务闭环。",
        "gate": "指定版本可复现运行，异常和人工交接路径完整",
        "steps": [
          {
            "id": "build-contract",
            "title": "落实数据与工具契约",
            "action": "定义接口字段、只读账号与失败重试规则。",
            "output": "数据契约与集成记录",
            "question": "接口挂了，业务还能怎么走？"
          },
          {
            "id": "build-implement",
            "title": "实现业务闭环",
            "action": "实现房态解释、交接提醒与状态校验主链路。",
            "output": "原型代码与版本说明",
            "question": "一线能否一步完成，不用离场补录？"
          },
          {
            "id": "build-failure",
            "title": "实现异常与审计",
            "action": "实现人工复核队列、具名接收与审计留痕。",
            "output": "异常处理与审计样例",
            "question": "异常发生时，谁在什么时间接收？"
          }
        ]
      },
      {
        "id": "validation",
        "title": "测试评估",
        "goal": "用可复现的评估集证明效果，同时暴露剩余风险。",
        "gate": "评估范围、版本、失败项、修复复测与剩余风险可审查",
        "steps": [
          {
            "id": "validation-evalset",
            "title": "建立评估集合",
            "action": "按房态场景与异常类型构造评估样本。",
            "output": "评估集与需求覆盖表",
            "question": "评估集覆盖了哪些异常路径？"
          },
          {
            "id": "validation-execute",
            "title": "执行测试与重复评估",
            "action": "多轮执行并记录版本、结果与波动。",
            "output": "测试报告与评估结果",
            "question": "结果稳定吗？差几次能复现？"
          },
          {
            "id": "validation-repair",
            "title": "修复并回归确认",
            "action": "缺陷闭环、复测与质量结论。",
            "output": "缺陷闭环与质量结论",
            "question": "哪些问题不带进试点？"
          }
        ]
      },
      {
        "id": "pilot",
        "title": "客户试点",
        "goal": "在受控范围内验证真实业务价值与可用性。",
        "gate": "试点对照、用户反馈、退出条件与扩大范围决定有记录",
        "steps": [
          {
            "id": "pilot-prepare",
            "title": "准备受控试点",
            "action": "锁定试点窗口、对照口径与退出条件。",
            "output": "试点执行计划",
            "question": "什么时候算失败，什么时候停？"
          },
          {
            "id": "pilot-uat",
            "title": "开展用户验收",
            "action": "按班次走查，记录现场反馈与绕过行为。",
            "output": "用户验收与反馈记录",
            "question": "一线在什么时候选择不用它？"
          },
          {
            "id": "pilot-value",
            "title": "核对价值与继续决定",
            "action": "对照基线与试点数据，出继续/扩大/停止的纪要。",
            "output": "试点收益复核与决策纪要",
            "question": "收益扣掉复核成本后还剩多少？"
          }
        ]
      },
      {
        "id": "handoff",
        "title": "上线交接",
        "goal": "让业务、技术和风险三方都能独立接手。",
        "gate": "业务、技术和风险角色的上线准备及交接决定有依据",
        "steps": [
          {
            "id": "handoff-readiness",
            "title": "审查上线准备",
            "action": "检查权限、监控、回滚与培训是否就位。",
            "output": "上线准备检查与三方评审",
            "question": "出事时谁第一个被叫？"
          },
          {
            "id": "handoff-release",
            "title": "演练发布与回滚",
            "action": "在预发环境演练发布、回滚与降级。",
            "output": "发布计划与回滚演练记录",
            "question": "回滚要多久，业务能接受吗？"
          },
          {
            "id": "handoff-transfer",
            "title": "完成运维和用户交接",
            "action": "移交运行手册、账号与值班表，签收确认。",
            "output": "交接清单、运行手册与签收记录",
            "question": "接收方真的能独立操作吗？"
          }
        ]
      },
      {
        "id": "operation",
        "title": "运营迭代",
        "goal": "把一次性交付变成可持续运行的运营节奏。",
        "gate": "运营节奏、事件闭环、复盘及下一轮优先级已确认",
        "steps": [
          {
            "id": "operation-observe",
            "title": "建立持续运营节奏",
            "action": "定义周度、月度观察指标与责任人。",
            "output": "30/60/90 天运营计划",
            "question": "哪个指标下跌就说明功能退化了？"
          },
          {
            "id": "operation-incident",
            "title": "演练事件与变更管理",
            "action": "演练误判、系统故障与口径变更的处理链路。",
            "output": "事件复盘与变更记录",
            "question": "口径变了，规则多久能同步？"
          },
          {
            "id": "operation-iterate",
            "title": "复盘并启动下一轮发现",
            "action": "形成复盘结论，列出下一轮迭代优先级。",
            "output": "项目复盘、迭代清单与作品集",
            "question": "下一轮最该改的是哪一件事？"
          }
        ]
      }
    ]
  },
  "rooms": {
    "hotel": "山海旅居 · 示范楼层",
    "rooms": [
      {
        "no": "1201",
        "type": "高级大床房",
        "floor": 12,
        "occupied": false,
        "clean": "dirty",
        "block": null,
        "note": "客人 10:12 退房"
      },
      {
        "no": "1202",
        "type": "高级大床房",
        "floor": 12,
        "occupied": false,
        "clean": "clean",
        "block": null,
        "note": "已清扫，待查房"
      },
      {
        "no": "1203",
        "type": "高级大床房",
        "floor": 12,
        "occupied": false,
        "clean": "inspected",
        "block": null,
        "note": "查房通过"
      },
      {
        "no": "1205",
        "type": "豪华双床房",
        "floor": 12,
        "occupied": false,
        "clean": "clean",
        "block": null,
        "note": "查房时发现卫浴异味"
      },
      {
        "no": "1206",
        "type": "豪华双床房",
        "floor": 12,
        "occupied": true,
        "clean": "dirty",
        "block": null,
        "note": "在住，预计明日退房"
      },
      {
        "no": "1207",
        "type": "高级大床房",
        "floor": 12,
        "occupied": false,
        "clean": "inspected",
        "block": {
          "type": "OOS",
          "reason": "床头灯待更换",
          "until": "今日 18:00"
        },
        "note": "可售但需提示"
      },
      {
        "no": "1208",
        "type": "家庭套房",
        "floor": 12,
        "occupied": false,
        "clean": "dirty",
        "block": {
          "type": "OOO",
          "reason": "空调故障大修",
          "until": "10-26"
        },
        "note": "已从库存扣减"
      },
      {
        "no": "1209",
        "type": "家庭套房",
        "floor": 12,
        "occupied": false,
        "clean": "clean",
        "block": null,
        "note": "查房未完成，前台已收到渠道订单"
      }
    ],
    "rules": [
      {
        "id": "R1",
        "text": "查房未通过（clean 而非 inspected）不得标记可售",
        "type": "确定性校验"
      },
      {
        "id": "R2",
        "text": "OOO 房间不进入可售库存，任何渠道不可分配",
        "type": "确定性校验"
      },
      {
        "id": "R3",
        "text": "OOS 房间可售但须在交接单提示原因与恢复时间",
        "type": "提示"
      },
      {
        "id": "R4",
        "text": "解除 OOO 必须有复审证据字段，缺失即拒绝恢复",
        "type": "确定性校验"
      },
      {
        "id": "R5",
        "text": "误判认定须由质检按签字口径判定，系统只提供证据",
        "type": "人工裁决"
      },
      {
        "id": "R6",
        "text": "交接单字段不超过现有单据填写时长，否则高峰必被绕过",
        "type": "可用性约束"
      }
    ],
    "handoffFields": [
      {
        "key": "room",
        "label": "房号",
        "required": true
      },
      {
        "key": "state",
        "label": "当前三态",
        "required": true
      },
      {
        "key": "blocker",
        "label": "阻塞原因",
        "required": false
      },
      {
        "key": "owner",
        "label": "具名接收人",
        "required": true
      },
      {
        "key": "nextAction",
        "label": "下一步动作",
        "required": true
      },
      {
        "key": "eta",
        "label": "预计可售时间",
        "required": false
      }
    ]
  }
};
