# ES 索引字段含义对照表

## checkin_record_es_2026

| 字段名 | 类型 | 含义 |
|--------|------|------|
| CC | text (+keyword) | 车次 |
| CPLX | text (+keyword) | 车票类型 |
| CPXM | text (+keyword) | 乘车人姓名 |
| CPZJH | text (+keyword) | 乘车人证件号 |
| CXH | text (+keyword) | 车厢号 |
| FCSJ | text (+keyword) | 发车时间 |
| FZ | text (+keyword) | 发站 |
| FZRQ | date | 发证日期 |
| IPDZ | text (+keyword) | IP地址 |
| JPCZ | text (+keyword) | 检票车站 |
| JPSJ | text (+keyword) | 检票时间 |
| JZJPCK | text (+keyword) | 进站检票口 |
| KKLX | text (+keyword) | 卡口类型 |
| MZ | text (+keyword) | 民族 |
| PH | text (+keyword) | 铺号 |
| QD | text (+keyword) | 起点 |
| SFZH | text (+keyword) | 身份证号 |
| SFZHZPDZ | text (+keyword) | 身份证照片地址 |
| SFZLX | text (+keyword) | 身份证类型 |
| SPC | text (+keyword) | 座位铺次 |
| SPCK | text (+keyword) | 座位铺次库 |
| TGKKDM | text (+keyword) | 通过卡口代码 |
| TGKKMC | text (+keyword) | 通过卡口名称 |
| TGSJ | date | 通过时间 |
| TJSJ | date | 添加时间 |
| XCGJTX1DZ | text (+keyword) | 行程轨迹推送地址1 |
| XCGJTX2DZ | text (+keyword) | 行程轨迹推送地址2 |
| XCGJTX3DZ | text (+keyword) | 行程轨迹推送地址3 |
| XCGJTXS | text (+keyword) | 行程轨迹推送数 |
| XLH | text (+keyword) | 序列号 |
| XM | text (+keyword) | 姓名 |
| YWRKSJ | text (+keyword) | 业务入库时间 |
| ZDZ | text (+keyword) | 站点地址 |
| ZWH | text (+keyword) | 座位号 |
| ZWLX | text (+keyword) | 座位类型 |
| boardTrainCode | text (+keyword) | 乘车车次 |
| bz1 | text (+keyword) | 备注1 |
| bz2 | text (+keyword) | 备注2 |
| bz3 | text (+keyword) | 备注3 |
| bz4 | text (+keyword) | 备注4 |
| bz5 | text (+keyword) | 备注5 |
| createTime | date | 创建时间 |
| docId | text (+keyword) | 文档ID |
| dt | text (+keyword) | 数据时间 |
| exitStation | keyword | 出站站名 |
| fromStationName | text (+keyword) | 出发站名 |
| gInserttime | date | 入库时间 |
| gender | keyword | 性别 |
| iBirthday | date | 出生日期 |
| id | text (+keyword) | ID |
| idName | text (+keyword) | 姓名 |
| idNo | keyword | 证件号 |
| jgEdgeSync | boolean | 轨迹边同步 |
| jgEventSync | boolean | 事件同步 |
| jgPersonSync | boolean | 人员同步 |
| jgSyncStatus | text (+keyword) | 同步状态 |
| jgSyncTime | date | 同步时间 |
| passTime | date | 通过时间 |
| result | keyword | 结果 |
| sChcode | keyword | 特征码 |
| sjkxd | text (+keyword) | 时间库携带 |
| sjly | text (+keyword) | 数据来源 |
| startDate | date | 开始日期 |
| stationName | text (+keyword) | 站名 |
| ticketNo | keyword | 票号 |
| toStationName | text (+keyword) | 到达站名 |
| trainNum | keyword | 车次号 |
| updateTime | date | 更新时间 |
| ywwybm | text (+keyword) | 业务唯一编码 |
| ztkRksjTs | long | 入库时间(特殊) |
| ztk_rksj | text (+keyword) | 入库时间 |

## crew_record_es_2026

| 字段名 | 类型 | 含义 |
|--------|------|------|
| FCRQ | date | 发车日期 |
| SFZ | text (+keyword) | 身份证 |
| ZDZ | text (+keyword) | 站点地址 |
| arrivalTime | date | 到达时间 |
| carrierCompany | text (+keyword) | 承运公司 |
| createTime | date | 创建时间 |
| crewCount | text (+keyword) | 乘务人数 |
| crewName | text (+keyword) | 乘务名称 |
| declaredValue | text (+keyword) | 申报价值 |
| docId | text (+keyword) | 文档ID |
| freightFee | text (+keyword) | 运费 |
| fromStationName | text (+keyword) | 出发站名 |
| idName | text (+keyword) | 姓名 |
| idNo | text (+keyword) | 证件号 |
| itemName | text (+keyword) | 项目名称 |
| itemStatus | text (+keyword) | 项目状态 |
| itemType | text (+keyword) | 项目类型 |
| leaderName | text (+keyword) | 负责人姓名 |
| loadStation | text (+keyword) | 装货站 |
| pieceCount | text (+keyword) | 件数 |
| receiverAddress | text (+keyword) | 收件人地址 |
| receiverIdCard | text (+keyword) | 收件人身份证 |
| receiverName | text (+keyword) | 收件人姓名 |
| receiverPhone | text (+keyword) | 收件人电话 |
| remark | text (+keyword) | 备注 |
| sendTime | date | 发货时间 |
| senderAddress | text (+keyword) | 寄件人地址 |
| senderIdCard | text (+keyword) | 寄件人身份证 |
| senderName | text (+keyword) | 寄件人姓名 |
| senderPhone | text (+keyword) | 寄件人电话 |
| sjlysd | text (+keyword) | 数据来源深度 |
| toStationName | text (+keyword) | 到达站名 |
| trainCode | text (+keyword) | 车次 |
| trainDate | date | 乘车日期 |
| unloadStation | text (+keyword) | 卸货站 |
| updateTime | date | 更新时间 |
| waybillNo | keyword | 运单号 |
| weight | text (+keyword) | 重量 |
| ztkRksjTs | long | 入库时间(特殊) |
| ztk_rksj | text (+keyword) | 入库时间 |

## person_info_es

| 字段名 | 类型 | 含义 |
|--------|------|------|
| CSRQ | date | 出生日期 |
| JG | keyword | 籍贯 |
| MZ | keyword | 民族 |
| RYWYBM | keyword | 人员唯一编码 |
| SFZZP | keyword | 身份证正照 |
| SJHM | keyword | 手机号码 |
| XB | keyword | 性别 |
| XM | text (+keyword) | 姓名 |
| ZJHM | keyword | 证件号码 |
| ZJLX | keyword | 证件类型 |
| ZJZP | keyword | 证件照片 |
| address | text (+keyword) | 地址 |
| birthDate | date | 出生日期 |
| birthplace | text (+keyword) | 出生地 |
| bz1 | keyword | 备注1 |
| bz2 | keyword | 备注2 |
| bz3 | keyword | 备注3 |
| bz4 | keyword | 备注4 |
| bz5 | keyword | 备注5 |
| createTime | date | 创建时间 |
| docId | text (+keyword) | 文档ID |
| ethnicity | text (+keyword) | 民族 |
| gender | text (+keyword) | 性别 |
| idCard | text (+keyword) | 身份证号 |
| idNo | text (+keyword) | 证件号 |
| infoUpdateTime | date | 信息更新时间 |
| name | text (+keyword) | 姓名 |
| personId | text (+keyword) | 人员ID |
| sjkxd | keyword | 时间库携带 |
| sjly | keyword | 数据来源 |
| updateTime | date | 更新时间 |
| ztkRksjTs | long | 入库时间(特殊) |
| ztk_rksj | keyword | 入库时间 |

## resign_record_es_2026

| 字段名 | 类型 | 含义 |
|--------|------|------|
| BC | text (+keyword) | 班次 |
| BZ1 | text (+keyword) | 备注1 |
| BZ2 | text (+keyword) | 备注2 |
| BZ3 | text (+keyword) | 备注3 |
| BZ4 | text (+keyword) | 备注4 |
| BZ5 | text (+keyword) | 备注5 |
| CC | text (+keyword) | 车次 |
| CPHM | text (+keyword) | 车票号码 |
| CPLB | text (+keyword) | 车票类别 |
| CPZT | text (+keyword) | 车票状态 |
| CSBY | text (+keyword) | 出生年月 |
| CXH | text (+keyword) | 车厢号 |
| CZBHDM | text (+keyword) | 车站编号代码 |
| DBM | text (+keyword) | 电报码 |
| DDJ | text (+keyword) | 到达时刻 |
| DDSR | float | 到达收入 |
| DLF | float | 到留费 |
| DT | text (+keyword) | 动态 |
| DTX2LPJ | float | 动态线路2票价 |
| DTXL1 | text (+keyword) | 动态线路1 |
| DTXL1LC | long | 动态线路1里程 |
| DTXL1PJ | float | 动态线路1票价 |
| DTXL2 | text (+keyword) | 动态线路2 |
| DTXL2LC | long | 动态线路2里程 |
| DTXL3 | text (+keyword) | 动态线路3 |
| DTXL3LC | long | 动态线路3里程 |
| DTXL3PJ | float | 动态线路3票价 |
| DTXL4 | text (+keyword) | 动态线路4 |
| DTXL4LC | long | 动态线路4里程 |
| DTXL4PJ | float | 动态线路4票价 |
| DTXL5 | text (+keyword) | 动态线路5 |
| DTXL5LC | long | 动态线路5里程 |
| DTXL5PJ | float | 动态线路5票价 |
| DYCGC | long | 第一乘车 |
| DYGFJDM | text (+keyword) | 单元股份代码 |
| DYJJDM | text (+keyword) | 单元机检代码 |
| FCRQ | date | 发车日期 |
| FCSJ | text (+keyword) | 发车时间 |
| FJF | float | 附加费 |
| FSZCKH | text (+keyword) | 发售站窗口号 |
| FSZDM | text (+keyword) | 发售站代码 |
| FWF | float | 服务费 |
| GP | float | 高铁票 |
| GQBC | text (+keyword) | 改签班次 |
| GQCK | text (+keyword) | 改签窗口 |
| GQCZM | text (+keyword) | 改签车站名 |
| GQCZYH | text (+keyword) | 改签操作员号 |
| GQFSZDM | text (+keyword) | 改签发售站代码 |
| GQJE | float | 改签金额 |
| GQJYBH | text (+keyword) | 改签交易编号 |
| GQJZRQ | date | 改签截止日期 |
| GQPH | text (+keyword) | 改签铺号 |
| GQPJ | float | 改签票价 |
| GQSJ | date | 改签时间 |
| GQZS | long | 改签张数 |
| HCH | text (+keyword) | 候车室 |
| ID | text (+keyword) | ID |
| JCPJ | float | 检票票价 |
| JXSPSJ | date | 检修视频时间 |
| JYH | text (+keyword) | 交易号 |
| JYQP | date | 交易车票 |
| JYZ | text (+keyword) | 检票站 |
| KTF | float | 空调费 |
| KTHCF | text (+keyword) | 空调候车费 |
| KTHCH | float | 空调候车号 |
| LC | long | 里程 |
| LSH | text (+keyword) | 流水号 |
| PH | text (+keyword) | 铺号 |
| PJ | float | 票价 |
| PJCE | float | 票据面额 |
| PY | text (+keyword) | 拼音 |
| RJKWD | text (+keyword) | 软件卡位 |
| ROYDBM | text (+keyword) | 人员唯一编码 |
| SCFJM | text (+keyword) | 上传房间码 |
| SCJDBM | text (+keyword) | 上传基地代码 |
| SCJM | text (+keyword) | 上传机码 |
| SCZWLX | text (+keyword) | 生成座位类型 |
| SFZ | text (+keyword) | 身份证 |
| SPRQ | date | 审批日期 |
| SPSJ | date | 审批时间 |
| SPSJ_SFM | text (+keyword) | 审批时间秒 |
| SWDH | text (+keyword) | 商务电话 |
| SYGFJDM | text (+keyword) | 收益股份代码 |
| SYGJDM | text (+keyword) | 收益国际代码 |
| SYZLXFS | text (+keyword) | 适用资料类型方式 |
| SYZMC | text (+keyword) | 适用证明名称 |
| SZZM | text (+keyword) | 使用证明 |
| TJBY | text (+keyword) | 添加备用 |
| TJBZ | text (+keyword) | 添加备注 |
| WDF | float | 无座费 |
| WPLB | text (+keyword) | 卧铺类别 |
| WTBY | text (+keyword) | 问题备用 |
| WYBJ | boolean | 五一标记 |
| XCFJM | text (+keyword) | 现场发检码 |
| XCJDBM | text (+keyword) | 现场基地代码 |
| XCJM | text (+keyword) | 现场机码 |
| XCQD | text (+keyword) | 行程起点 |
| XSBY | text (+keyword) | 销售备用 |
| XSQD | text (+keyword) | 销售起点 |
| YH | text (+keyword) | 银行 |
| YHJG | float | 银行机构 |
| YHL | long | 银行行号 |
| YHLX | text (+keyword) | 银行类型 |
| YL12 | text (+keyword) | 预留12 |
| YL13 | text (+keyword) | 预留13 |
| YL14 | text (+keyword) | 预留14 |
| YL15 | text (+keyword) | 预留15 |
| YL16 | text (+keyword) | 预留16 |
| YLC | long | 预留车次 |
| YLDW | text (+keyword) | 预留单位 |
| YPJ | long | 原票价 |
| YPLX | text (+keyword) | 原票类型 |
| YSLB | text (+keyword) | 原收类别 |
| YSZM | text (+keyword) | 原始证明 |
| ZDZ | text (+keyword) | 站点地址 |
| ZK | float | 站口 |
| ZWH | text (+keyword) | 座位号 |
| ZWLXDM | text (+keyword) | 座位类型代码 |
| ZZZDBM | text (+keyword) | 中转站代码 |
| boardTrainCode | text (+keyword) | 乘车车次 |
| coachNo | text (+keyword) | 车厢号 |
| createTime | date | 创建时间 |
| docId | text (+keyword) | 文档ID |
| fromStationName | text (+keyword) | 出发站名 |
| idName | text (+keyword) | 姓名 |
| idNo | keyword | 证件号 |
| officeNo | text (+keyword) | 窗口号 |
| resignCost | double | 改签费用 |
| resignSaleTime | date | 改签售票时间 |
| resignTicketNo | text (+keyword) | 改签票号 |
| resignTicketPrice | double | 改签票价 |
| saleTime | date | 售票时间 |
| seatNo | text (+keyword) | 座位号 |
| sjly | text (+keyword) | 数据来源 |
| sjlysd | text (+keyword) | 数据来源深度 |
| startTime | text (+keyword) | 开始时间 |
| ticketNo | keyword | 票号 |
| ticketPrice | double | 票价 |
| toStationName | text (+keyword) | 到达站名 |
| trainDate | date | 乘车日期 |
| updateTime | date | 更新时间 |
| ztkRksjTs | long | 入库时间(特殊) |
| ztk_rksj | text (+keyword) | 入库时间 |

## return_record_es_2026

| 字段名 | 类型 | 含义 |
|--------|------|------|
| BC | text (+keyword) | 班次 |
| BJ | float | 报警 |
| BZ1 | text (+keyword) | 备注1 |
| BZ2 | text (+keyword) | 备注2 |
| BZ3 | text (+keyword) | 备注3 |
| BZ4 | text (+keyword) | 备注4 |
| BZ5 | text (+keyword) | 备注5 |
| CC | text (+keyword) | 车次 |
| CPHM | text (+keyword) | 车票号码 |
| CPLB | text (+keyword) | 车票类别 |
| CSBY | text (+keyword) | 出生年月 |
| CXH | text (+keyword) | 车厢号 |
| CZBHDM | text (+keyword) | 车站编号代码 |
| DBM | text (+keyword) | 电报码 |
| DDJ | text (+keyword) | 到达时刻 |
| DDSR | float | 到达收入 |
| DLF | float | 到留费 |
| DT | text (+keyword) | 动态 |
| DTX2LPJ | float | 动态线路2票价 |
| DTXL1 | text (+keyword) | 动态线路1 |
| DTXL1LC | long | 动态线路1里程 |
| DTXL1PJ | float | 动态线路1票价 |
| DTXL2 | text (+keyword) | 动态线路2 |
| DTXL2LC | long | 动态线路2里程 |
| DTXL3 | text (+keyword) | 动态线路3 |
| DTXL3LC | long | 动态线路3里程 |
| DTXL3PJ | float | 动态线路3票价 |
| DTXL4 | text (+keyword) | 动态线路4 |
| DTXL4LC | long | 动态线路4里程 |
| DTXL4PJ | float | 动态线路4票价 |
| DTXL5 | text (+keyword) | 动态线路5 |
| DTXL5LC | long | 动态线路5里程 |
| DTXL5PJ | float | 动态线路5票价 |
| DYGFJDM | text (+keyword) | 单元股份代码 |
| DYJJDM | text (+keyword) | 单元机检代码 |
| FCRQ | date | 发车日期 |
| FCSJ | text (+keyword) | 发车时间 |
| FJF | float | 附加费 |
| FSZCKH | text (+keyword) | 发售站窗口号 |
| FSZDM | text (+keyword) | 发售站代码 |
| FWF | float | 服务费 |
| GS | text (+keyword) | 公司 |
| HCH | text (+keyword) | 候车室 |
| JCPJ | float | 检票票价 |
| JY | text (+keyword) | 交易 |
| JYH | text (+keyword) | 交易号 |
| JYQP | date | 交易车票 |
| JYZ | text (+keyword) | 检票站 |
| KT | text (+keyword) | 客车类型 |
| KTF | float | 空调费 |
| LC | long | 里程 |
| LSCC1 | text (+keyword) | 历史车次1 |
| LYDM | text (+keyword) | 来源代码 |
| PH | text (+keyword) | 铺号 |
| PJ | float | 票价 |
| QJ | float | 区间 |
| QTF | float | 其他费 |
| RJKWD | text (+keyword) | 软件卡位 |
| ROYDBM | text (+keyword) | 人员唯一编码 |
| SCFJM | text (+keyword) | 上传房间码 |
| SCJM | text (+keyword) | 上传机码 |
| SFZ | text (+keyword) | 身份证 |
| SFZDBM | text (+keyword) | 身份证代码 |
| SPCH | text (+keyword) | 售票车次 |
| SPCKH | text (+keyword) | 座位铺次库号 |
| SPRQ | date | 审批日期 |
| SPSJ | text (+keyword) | 审批时间 |
| SPYDM | text (+keyword) | 售票员代码 |
| SWDH | text (+keyword) | 商务电话 |
| SYGFJDM | text (+keyword) | 收益股份代码 |
| SYGJDM | text (+keyword) | 收益国际代码 |
| SYZLXFS | text (+keyword) | 适用资料类型方式 |
| SYZMC | text (+keyword) | 适用证明名称 |
| SZZM | text (+keyword) | 使用证明 |
| TDID | text (+keyword) | 通道ID |
| TJBY | text (+keyword) | 添加备用 |
| TJBZ | text (+keyword) | 添加备注 |
| TJXLH | long | 添加序列号 |
| TPCS | float | 退票张数 |
| TPJE | float | 退票金额 |
| TPRQ | date | 退票日期 |
| TPSJ | text (+keyword) | 退票时间 |
| TPYY | text (+keyword) | 退票原因 |
| TPZT | text (+keyword) | 退票状态 |
| WDF | float | 无座费 |
| WPLB | text (+keyword) | 卧铺类别 |
| WTBY | text (+keyword) | 问题备用 |
| WYBJ | text (+keyword) | 五一标记 |
| XCFJM | text (+keyword) | 现场发检码 |
| XCJM | text (+keyword) | 现场机码 |
| XSQD | text (+keyword) | 销售起点 |
| YH | text (+keyword) | 银行 |
| YHJG | float | 银行机构 |
| YHL | long | 银行行号 |
| YHLX | text (+keyword) | 银行类型 |
| YL12 | text (+keyword) | 预留12 |
| YL13 | text (+keyword) | 预留13 |
| YL14 | text (+keyword) | 预留14 |
| YL15 | text (+keyword) | 预留15 |
| YL16 | text (+keyword) | 预留16 |
| YLC | long | 预留车次 |
| YPJ | float | 原票价 |
| YPLX | text (+keyword) | 原票类型 |
| YSLB | text (+keyword) | 原收类别 |
| YSZM | text (+keyword) | 原始证明 |
| ZDZ | text (+keyword) | 站点地址 |
| ZDZDBM | text (+keyword) | 站点代码 |
| ZFPJ | float | 作废票价 |
| ZJL | long | 证件号码 |
| ZK | float | 站口 |
| ZWH | text (+keyword) | 座位号 |
| ZWLXDM | text (+keyword) | 座位类型代码 |
| ZZZDBM | text (+keyword) | 中转站代码 |
| ZZZFPJ | float | 中转作废票价 |
| boardTrainCode | text (+keyword) | 乘车车次 |
| coachNo | text (+keyword) | 车厢号 |
| createTime | date | 创建时间 |
| docId | text (+keyword) | 文档ID |
| fromStationName | text (+keyword) | 出发站名 |
| idName | text (+keyword) | 姓名 |
| idNo | keyword | 证件号 |
| returnCost | double | 退票费用 |
| returnDate | date | 退票日期 |
| returnReason | text (+keyword) | 退票原因 |
| returnState | text (+keyword) | 退票状态 |
| returnTime | text (+keyword) | 退票时间 |
| returnTotal | double | 退票总额 |
| seatNo | text (+keyword) | 座位号 |
| sjly | text (+keyword) | 数据来源 |
| sjlysd | text (+keyword) | 数据来源深度 |
| startTime | text (+keyword) | 开始时间 |
| ticketNo | keyword | 票号 |
| ticketOfficeNo | text (+keyword) | 售票窗口号 |
| ticketPrice | double | 票价 |
| ticketSaleDate | date | 售票日期 |
| ticketType | text (+keyword) | 车票类型 |
| ticketWindowNo | text (+keyword) | 售票窗口号 |
| toStationName | text (+keyword) | 到达站名 |
| trainDate | date | 乘车日期 |
| updateTime | date | 更新时间 |
| ztkRksjTs | long | 入库时间(特殊) |
| ztk_rksj | text (+keyword) | 入库时间 |

## ticket_record_es_2026

| 字段名 | 类型 | 含义 |
|--------|------|------|
| BZ | text (+keyword) | 备注 |
| BZ1 | text (+keyword) | 备注1 |
| BZ2 | text (+keyword) | 备注2 |
| BZ3 | text (+keyword) | 备注3 |
| BZ4 | text (+keyword) | 备注4 |
| BZ5 | text (+keyword) | 备注5 |
| CC | text (+keyword) | 车次 |
| CPHM | text (+keyword) | 车票号码 |
| CPLX | text (+keyword) | 车票类型 |
| CXH | text (+keyword) | 车厢号 |
| DDXH | text (+keyword) | 到达序号 |
| DPRCSRQ | date | 订票人生日 |
| DPRDZYJ | text (+keyword) | 订票人电子邮箱 |
| DPRGJ | text (+keyword) | 订票人国籍 |
| DPRSJH | text (+keyword) | 订票人手机号 |
| DPRXB | text (+keyword) | 订票人性别 |
| DPRXM | text (+keyword) | 订票人姓名 |
| DPRZH | text (+keyword) | 订票人账号 |
| DPRZJH | text (+keyword) | 订票人证件号 |
| DPRZJHM | text (+keyword) | 订票人证件号码 |
| DT | text (+keyword) | 动态 |
| FCRQ | date | 发车日期 |
| GPQDLX | text (+keyword) | 高铁区段类型 |
| GPQDMC | text (+keyword) | 高铁区段名称 |
| LKXM | text (+keyword) | 旅客姓名 |
| LKZJHM | text (+keyword) | 旅客证件号码 |
| PH | text (+keyword) | 铺号 |
| PJ | text (+keyword) | 票价 |
| SFZ | text (+keyword) | 身份证 |
| SJKXD | text (+keyword) | 时间库携带 |
| ZDZ | text (+keyword) | 站点地址 |
| ZJLX | text (+keyword) | 证件类型 |
| ZTK_RKSJ | text (+keyword) | 入库时间 |
| ZWH | text (+keyword) | 座位号 |
| ZWLX | text (+keyword) | 座位类型 |
| _test_field | text (+keyword) | 测试字段 |
| area | keyword | 地区 |
| boardTrainCode | keyword | 乘车车次 |
| bornDate | date | 出生日期 |
| checkinTime | text (+keyword) | 进站时间 |
| coachNo | keyword | 车厢号 |
| country | text (+keyword) | 国家 |
| createTime | date | 创建时间 |
| distance | integer | 距离 |
| docId | text (+keyword) | 文档ID |
| dpsj | text (+keyword) | 到票时间 |
| email | text (+keyword) | 邮箱 |
| endDate | text (+keyword) | 结束日期 |
| endStation | text (+keyword) | 终点站 |
| fromBureau | keyword | 出发局 |
| fromStationName | text (+keyword) | 出发站名 |
| gender | keyword | 性别 |
| idCard | text (+keyword) | 身份证号 |
| idKindNew | keyword | 证件类型(新) |
| idName | text (+keyword) | 姓名 |
| idNo | keyword | 证件号 |
| isLateNightRide | boolean | 是否深夜乘车 |
| isLimitHigh | boolean | 是否限高 |
| isNightRide | boolean | 是否夜间乘车 |
| jgEdgeSync | boolean | 轨迹边同步 |
| jgPersonSync | boolean | 人员同步 |
| jgSyncStatus | text (+keyword) | 同步状态 |
| jgSyncTime | date | 同步时间 |
| jgTripSync | boolean | 行程同步 |
| mobileNo | text (+keyword) | 手机号码 |
| neighborRelation | text (+keyword) | 邻座关系 |
| officeName | text (+keyword) | 窗口名称 |
| officeNo | keyword | 窗口号 |
| orderNo | text (+keyword) | 订单号 |
| passengerIdNo | text (+keyword) | 旅客证件号 |
| passengerName | text (+keyword) | 旅客姓名 |
| personName | text (+keyword) | 人员姓名 |
| realName | text (+keyword) | 真实姓名 |
| reserveTime | text (+keyword) | 预约时间 |
| rywybm | text (+keyword) | 人员唯一编码 |
| saleMode | keyword | 售票方式 |
| saleTime | date | 售票时间 |
| seatNo | keyword | 座位号 |
| seatType | text (+keyword) | 座位类型 |
| seatTypeCodeNew | keyword | 座位类型代码(新) |
| seatTypeName | text (+keyword) | 座位类型名称 |
| sequenceNo | text (+keyword) | 序列号 |
| sex | text (+keyword) | 性别 |
| sjly | text (+keyword) | 数据来源 |
| sjlysd | keyword | 数据来源深度 |
| startDate | text (+keyword) | 开始日期 |
| startStation | text (+keyword) | 出发站 |
| startTime | keyword | 开始时间 |
| test | text (+keyword) | 测试 |
| test_field | text (+keyword) | 测试字段 |
| ticketKind | keyword | 车票种类 |
| ticketNo | keyword | 票号 |
| ticketPrice | double | 票价 |
| ticketStatus | long | 车票状态 |
| ticketTypeName | text (+keyword) | 车票类型名称 |
| ticketTypeNew | keyword | 车票类型(新) |
| timeToDeparture | long | 距发车时间 |
| toBureau | keyword | 到达局 |
| toStationName | text (+keyword) | 到达站名 |
| trainBureau | keyword | 铁路局 |
| trainCode | text (+keyword) | 车次 |
| trainDate | date | 乘车日期 |
| trainType | text (+keyword) | 车型 |
| updateTime | date | 更新时间 |
| userName | text (+keyword) | 用户名 |
| windowNo | keyword | 窗口号 |
| ztkRksjTs | long | 入库时间(特殊) |

## zdry_info_es

| 字段名 | 类型 | 含义 |
|--------|------|------|
| SFZZP | text (+keyword) | 身份证正照 |
| asjbh | text (+keyword) | 案事件编号 |
| bmch | text (+keyword) | 部门名称 |
| bz1 | keyword | 备注1 |
| bz2 | keyword | 备注2 |
| bz3 | keyword | 备注3 |
| bz4 | keyword | 备注4 |
| bz5 | keyword | 备注5 |
| createTime | date | 创建时间 |
| csrq | date | 出生日期 |
| docId | text (+keyword) | 文档ID |
| gkcs | keyword | 关口次数 |
| gkjzsj | keyword | 关口进站时间 |
| gkkssj | date | 关口开始时间 |
| gkmjdh | keyword | 关口民警电话 |
| gkyj | text (+keyword) | 关口预警 |
| gkzt | keyword | 关口状态 |
| hjdzDzmc | text (+keyword) | 户籍地址名称 |
| idCard | text (+keyword) | 身份证号 |
| infoUpdateTime | date | 信息更新时间 |
| ladwGajgjgdm | text (+keyword) | 落案单位公安机构代码 |
| mzdm | text (+keyword) | 民族代码 |
| personTypeCode | long | 人员类型代码 |
| personTypeName | text (+keyword) | 人员类型名称 |
| reason | text (+keyword) | 原因 |
| rywybm | keyword | 人员唯一编码 |
| sfzh | text (+keyword) | 身份证号 |
| sjkxd | keyword | 时间库携带 |
| sjly | keyword | 数据来源 |
| tjjbdm | text (+keyword) | 统计指标代码 |
| tpsj | date | 退票时间 |
| updateTime | date | 更新时间 |
| wxdj | keyword | 维修登记 |
| xbdm | text (+keyword) | 性别代码 |
| xm | text (+keyword) | 姓名 |
| xzzDzmc | text (+keyword) | 现住址名称 |
| zbrLxdh | text (+keyword) | 主办人联系电话 |
| zbrXm | text (+keyword) | 主办人姓名 |
| zdrycym | keyword | 重点人员曾用名 |
| zdryfl | keyword | 重点人员分类 |
| zdryhjdz | text (+keyword) | 重点人员户籍地址 |
| zdryjg | keyword | 重点人员籍贯 |
| zdrylb | text (+keyword) | 重点人员类别 |
| zdrylxdh | text (+keyword) | 重点人员联系电话 |
| zdrymz | text (+keyword) | 重点人员民族 |
| zdryxb | text (+keyword) | 重点人员性别 |
| zdryxl | keyword | 重点人员学历 |
| zdryxm | text (+keyword) | 重点人员姓名 |
| zdryxzd | text (+keyword) | 重点人员现住地 |
| zjhm | text (+keyword) | 证件号码 |
| zjlx | keyword | 证件类型 |
| zrdwdm | text (+keyword) | 责任单位代码 |
| zrdwmc | keyword | 责任单位名称 |
| zrmjxm | text (+keyword) | 责任民警姓名 |
| ztjj | text (+keyword) | 状态简记 |
| ztkRksjTs | long | 入库时间(特殊) |
| ztk_rksj | keyword | 入库时间 |
| ztrybh | text (+keyword) | 重点人员编号 |
| ztrylxdm | text (+keyword) | 重点人员类型代码 |
