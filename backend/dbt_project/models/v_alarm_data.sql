-- DataPivot 宽表模型：将 6 表 JOIN 为扁平化分析视图
-- 供 databao agent 内省和查询使用

WITH joined AS (
    SELECT
        t.CREATE_BY                          AS "人员",
        vt.VEHICLETYPE_NAME                  AS "车型",
        tv.VIN                               AS "车辆",
        t.TASK_NAME                          AS "任务",
        tr.RULE_NAME                         AS "规则名称",
        CASE tr.RULE_TYPE
            WHEN 0 THEN '统计'
            WHEN 1 THEN '报警'
            WHEN 2 THEN '事件'
            ELSE '未知'
        END                                   AS "规则类型",
        rr.TIME                              AS "报警时间",
        rr.TRIGGER_TIME                      AS "触发时间",
        TRY_CAST(COALESCE(rr.VALUE, '0') AS DOUBLE) AS "持续时间",
        rr.TASK_RULE_RESULT_ID               AS "报警结果ID",
        tr.TASK_RULE_ID                      AS "规则ID",
        t.TASK_ID                            AS "任务ID"
    FROM TM_RMU_PS_TASK t
    JOIN TM_RMU_PS_TASK_VEHICLETYPE vt ON t.TASK_ID = vt.TASK_ID
    JOIN TM_RMU_PS_TASK_VEHICLE tv ON t.TASK_ID = tv.TASK_ID
    JOIN TM_RMU_PS_TASK_RULE tr ON t.TASK_ID = tr.TASK_ID
    LEFT JOIN TL_RMU_PS_TASK_RULE_RESULT rr ON tr.TASK_RULE_ID = rr.TASK_RULE_ID
)

SELECT * FROM joined
