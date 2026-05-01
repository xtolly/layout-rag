namespace Leadsoft.Dto.Common;
/// <summary>
/// 箱柜类型
/// </summary>
public enum BoxClassifyEnum
{
    /// <summary>
    /// 配电箱
    /// </summary>
    [Description("配电箱")]
    DistributionBox,
    /// <summary>
    /// 户箱
    /// </summary>
    [Description("户箱")]
    HouseBox,
    /// <summary>
    /// 标准电表箱
    /// </summary>
    [Description("标准电表箱")]
    StandardElectricBox,
    /// <summary>
    /// 非标电表箱
    /// </summary>
    [Description("非标电表箱")]
    NotStandardElectricBox
}
/// <summary>
/// 进线方式
/// </summary>
public enum InLineModeEnum
{
    /// <summary>
    /// 进线器件上置
    /// </summary>
    [Description("进线器件上置")]
    InLineUp,
    /// <summary>
    /// 进线器件左置
    /// </summary>
    [Description("进线器件左置")]
    InLineLeft
}
/// <summary>
/// 固定方式
/// </summary>
public enum FixUpTypeEnum
{
    /// <summary>
    /// 板式安装
    /// </summary>
    [Description("板式安装")]
    FixUpPanel,
    /// <summary>
    /// 梁式安装
    /// </summary>
    [Description("梁式安装")]
    FixUpBridge
}
/// <summary>
/// 开门方式
/// </summary>
public enum DoorTypeEnum
{
    /// <summary>
    /// 左开门
    /// </summary>
    [Description("左开门")]
    OpenDoorLeft,
    /// <summary>
    /// 右开门
    /// </summary>
    [Description("右开门")]
    OpenDoorRight,
    /// <summary>
    /// 双开门
    /// </summary>
    [Description("双开门")]
    OpenDoorBoth
}
/// <summary>
/// 电缆进出方式
/// </summary>
public enum CableInOutTypeEnum
{
    /// <summary>
    /// 上进下出
    /// </summary>
    [Description("上进下出")]
    Null,
    /// <summary>
    /// 上进上出-左侧出线
    /// </summary>
    [Description("上进上出-左侧出线")]
    LeftOut,
    /// <summary>
    /// 上进上出-右侧出线
    /// </summary>
    [Description("上进上出-右侧出线")]
    RightOut,
    /// <summary>
    /// 下进下出-左侧进线
    /// </summary>
    [Description("下进下出-左侧进线")]
    LeftIn,
    /// <summary>
    /// 下进下出-右侧进线
    /// </summary>
    [Description("下进下出-右侧进线")]
    RightIn,
    /// <summary>
    /// 下进上出-左进右出
    /// </summary>
    [Description("下进上出-左进右出")]
    LeftInRightOut,
    /// <summary>
    /// 下进上出-右进左出
    /// </summary>
    [Description("下进上出-右进左出")]
    RightInLeftOut
}
/// <summary>
/// 双开门器件布置位置
/// </summary>
public enum DoubleDoorPartPositionEnum
{ 
    LeftDoor, 
    RightDoor 
}
public enum InstallTypeEnum 
{
    [Description("")]
    UnKnow = -1,
    /// <summary>
    /// 户内暗装
    /// </summary>
    [Description("户内暗装")]
    IndoorDarkSuit,
    /// <summary>
    /// 户内挂墙
    /// </summary>
    [Description("户内挂墙")]
    IndoorWall,
    /// <summary>
    /// 户内落地
    /// </summary>
    [Description("户内落地")]
    IndoorLand,
    /// <summary>
    /// 户外挂墙
    /// </summary>
    [Description("户外挂墙")]
    OutdoorWall,
    /// <summary>
    /// 户外落地
    /// </summary>
    [Description("户外落地")]
    OutdoorLand
}
public enum ComparisonEnum 
{
    /// <summary>
    /// 大于
    /// </summary>
    GreaterThan,
    /// <summary>
    /// 小于
    /// </summary>
    LessThan
}

