from nonebot import on_command, on_keyword, on_startswith, get_driver, on_regex
from nonebot.rule import to_me
from nonebot.matcher import Matcher
from nonebot.adapters import Message
from nonebot.params import Arg, ArgPlainText, CommandArg, Matcher
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageEvent, PrivateMessageEvent, MessageSegment, GroupMessageEvent, exception
from nonebot.typing import T_State  
import nonebot
import re
import json
import base64
import random
import subprocess
import sys
import os
from .task import offer, query, delete, handle_ocr_text, inverted2forward, findAlltag, addTag, delTag
from .config import Config
from nonebot.log import logger


plugin_config = Config.parse_obj(get_driver().config)

need_at = {}
if plugin_config.quote_needat:
    need_at['rule'] = to_me()


record_dict = {}
inverted_index = {}

# 首次运行时导入表
try:
    with open(plugin_config.record_path, 'r', encoding='UTF-8') as fr:
        record_dict = json.load(fr)

    with open(plugin_config.inverted_index_path, 'r', encoding='UTF-8') as fi:
        inverted_index = json.load(fi)
    logger.info('nonebot_plugin_quote路径配置成功')
except Exception as e:
    with open(plugin_config.record_path, 'w', encoding='UTF-8') as f:
        json.dump(record_dict, f, indent=2, separators=(',', ': '), ensure_ascii=False)

    with open(plugin_config.inverted_index_path, 'w', encoding='UTF-8') as fc:
        json.dump(inverted_index, fc, indent=2, separators=(',',': '), ensure_ascii=False)
    logger.warning('已创建json文件')


forward_index = inverted2forward(inverted_index)
# reply_index = {}


 # 语录库
record = on_command("{}上传".format(plugin_config.quote_startcmd), priority=10, block=True, rule=to_me())
end_conversation = ['stop', '结束', '上传截图', '结束上传']


@record.handle()
async def _(event: MessageEvent, args: Message = CommandArg()):
    if isinstance(event, PrivateMessageEvent):
        await record.finish()

    plain_text = args.extract_plain_text()
    if plain_text:
        record.set_arg("prompt", message=args)


@record.got("prompt", prompt="请上传语录(图片形式)")
async def record_upload(bot: Bot, event: MessageEvent, prompt: Message = Arg(), msg: Message = Arg("prompt")):

    global inverted_index
    global record_dict
    global forward_index

    session_id = event.get_session_id()
    message_id = event.message_id

    if str(msg) in end_conversation:
        await record.finish('上传会话已结束')

    rt = r"\[CQ:image,file=(.*?),subType=[\S]*,url=[\S]*\]"

    files = re.findall(rt, str(msg))

    if len(files) == 0:
        resp = "请上传图片"
        await record.reject_arg('prompt', MessageSegment.reply(message_id) + resp)

    resp =  await bot.call_api('get_image',  **{'file':files[0]})

    # OCR分词
    try:
        ocr = await bot.ocr_image(image=files[0])

        ocr_content = handle_ocr_text(ocr['texts'])
    except exception.ActionFailed:
        ocr_content = ''


    if 'group' in session_id:
        tmpList = session_id.split('_')
        groupNum = tmpList[1]

        resp['file'] = resp['file'].replace('data/','../')

        inverted_index, forward_index = offer(groupNum, resp['file'], ocr_content, inverted_index, forward_index)

        if groupNum not in record_dict:
            record_dict[groupNum] = [resp['file']]
        else:
            if resp['file'] not in record_dict[groupNum]:
                record_dict[groupNum].append(resp['file'])


        with open(plugin_config.record_path, 'w', encoding='UTF-8') as f:
            json.dump(record_dict, f, indent=2, separators=(',', ': '), ensure_ascii=False)

        with open(plugin_config.inverted_index_path, 'w', encoding='UTF-8') as fc:
            json.dump(inverted_index, fc, indent=2, separators=(',',': '), ensure_ascii=False)

    # await record.reject_arg('prompt', MessageSegment.reply(message_id) + '上传成功')
    await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': MessageSegment.reply(message_id) + '上传成功'
        })
    await record.finish('上传会话已结束')


record_pool = on_startswith('{}语录'.format(plugin_config.quote_startcmd), priority=2, block=True, **need_at)


@record_pool.handle()
async def record_pool_handle(bot: Bot, event: Event, state: T_State):

    session_id = event.get_session_id()
    user_id = str(event.get_user_id())

    global inverted_index
    global record_dict

    if 'group' in session_id:

        search_info = str(event.get_message()).strip()
        search_info = search_info.replace('{}语录'.format(plugin_config.quote_startcmd),'').replace(' ','')

        tmpList = session_id.split('_')
        groupNum = tmpList[1]

        if search_info == '':
            if groupNum not in record_dict:
                msg = '当前无语录库'
            else:
                length = len(record_dict[groupNum])
                idx = random.randint(0, length-1)
                msg = '[CQ:image,file={}]'.format(record_dict[groupNum][idx])
        else:
            ret = query(search_info, groupNum, inverted_index)

            if ret['status'] == -1:
                msg = '当前无语录库'
            elif ret['status'] == 2:
                if groupNum not in record_dict:
                    msg = '当前无语录库'
                else:
                    length = len(record_dict[groupNum])
                    idx = random.randint(0, length-1)
                    msg = '当前查询无结果, 为您随机发送。\n[CQ:image,file={}]'.format(record_dict[groupNum][idx])
            elif ret['status'] == 1:
                msg = '[CQ:image,file={}]'.format(ret['msg'])
            else:
                msg = ret.text

        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': msg
        })

    await record_pool.finish()


record_help = on_keyword({"语录"}, priority=10, rule=to_me())

@record_help.handle()
async def record_help_handle(bot: Bot, event: Event, state: T_State):

    session_id = event.get_session_id()
    user_id = str(event.get_user_id())
    raw_msg = str(event.get_message())
    if '怎么用' not in raw_msg and '如何' not in raw_msg:
        await record_help.finish()

    msg = '''您可以通过at我+上传, 开启上传语录通道; 再发送图片上传语录。您也可以直接发送【语录】指令, 我将随机返回一条语录。'''

    if 'group' in session_id:
        tmpList = session_id.split('_')
        groupNum = tmpList[1]

        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + msg
        })

    await record_help.finish()


delete_record = on_command('{}删除'.format(plugin_config.quote_startcmd), aliases={'delete'}, **need_at)

@delete_record.handle()
async def delete_record_handle(bot: Bot, event: Event, state: T_State):

    global inverted_index
    global record_dict
    global forward_index

    session_id = event.get_session_id()
    user_id = str(event.get_user_id())

    if 'group' not in session_id:
        await delete_record.finish()
    
    groupNum = session_id.split('_')[1]
    if user_id not in plugin_config.global_superuser:
        if groupNum not in plugin_config.quote_superuser or user_id not in plugin_config.quote_superuser[groupNum]:  
            await bot.call_api('send_group_msg', **{
                'group_id':int(groupNum),
                'message': '[CQ:at,qq='+user_id+'] 非常抱歉, 您没有删除权限TUT'
            })
            await delete_record.finish()

    raw_message = str(event)

    errMsg = '请回复需要删除的语录, 并输入删除指令'

    rt = r"\[reply:id=(.*?)]"
    ids = re.findall(rt, str(raw_message))

    if len(ids) == 0:
        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + errMsg
        })
        await delete_record.finish()

    rlyid = ids[0].split(",")[0]
    resp = await bot.get_msg(message_id=rlyid)

    img_msg = str(resp['message'])

    rt = r"\[CQ:image,file=(.*?),subType=[\S]*,url=[\S]*\]"
    imgs = re.findall(rt, img_msg)

    if len(imgs) == 0:
        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + errMsg
        })
        await delete_record.finish()
    
    # 搜索
    is_Delete, record_dict, inverted_index, forward_index = delete(imgs[0], groupNum, record_dict, inverted_index, forward_index)

    if is_Delete:
        with open(plugin_config.record_path, 'w', encoding='UTF-8') as f:
            json.dump(record_dict, f, indent=2, separators=(',', ': '), ensure_ascii=False)
        with open(plugin_config.inverted_index_path, 'w', encoding='UTF-8') as fc:
            json.dump(inverted_index, fc, indent=2, separators=(',',': '), ensure_ascii=False)
        msg = '删除成功'
    else:
        msg = '该图不在语录库中'


    await bot.call_api('send_group_msg', **{
        'group_id':int(groupNum),
        'message': '[CQ:at,qq='+user_id+']' + msg
    })

    await delete_record.finish()



alltag = on_command('{}alltag'.format(plugin_config.quote_startcmd), aliases={'{}标签'.format(plugin_config.quote_startcmd),'{}tag'.format(plugin_config.quote_startcmd)}, **need_at)

@alltag.handle()
async def alltag_handle(bot: Bot, event: Event, state: T_State):

    global inverted_index
    global record_dict
    global forward_index

    session_id = event.get_session_id()
    user_id = str(event.get_user_id())

    if 'group' not in session_id:
        await alltag.finish()

    groupNum = session_id.split('_')[1]
    raw_message = str(event)

    errMsg = '请回复需要指定语录'

    rt = r"\[reply:id=(.*?)]"
    ids = re.findall(rt, str(raw_message))

    if len(ids) == 0:
        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + errMsg
        })
        await alltag.finish()

    rlyid = ids[0].split(",")[0]
    resp = await bot.get_msg(message_id=rlyid)

    img_msg = str(resp['message'])

    rt = r"\[CQ:image,file=(.*?),subType=[\S]*,url=[\S]*\]"
    imgs = re.findall(rt, img_msg)

    if len(imgs) == 0:
        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + errMsg
        })
        await alltag.finish()

    tags = findAlltag(imgs[0], forward_index, groupNum)
    if tags is None:
        msg = '该语录不存在'
    else:
        msg = '该语录的所有Tag为: '
        for tag in tags:
            msg += tag + ' '

    await bot.call_api('send_group_msg', **{
        'group_id':int(groupNum),
        'message': '[CQ:at,qq='+user_id+']' + msg
    })

    await alltag.finish()


addtag = on_regex(pattern="^{}addtag\ ".format(plugin_config.quote_startcmd), **need_at)

@addtag.handle()
async def addtag_handle(bot: Bot, event: Event, state: T_State):

    global inverted_index
    global record_dict
    global forward_index

    session_id = event.get_session_id()
    user_id = str(event.get_user_id())
    tags = str(event.get_message()).replace('{}addtag'.format(plugin_config.quote_startcmd), '').strip().split(' ')

    if 'group' not in session_id:
        await addtag.finish()

    groupNum = session_id.split('_')[1]
    raw_message = str(event)

    errMsg = '请回复需要指定语录'

    rt = r"\[reply:id=(.*?)]"
    ids = re.findall(rt, str(raw_message))

    if len(ids) == 0:
        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + errMsg
        })
        await addtag.finish()

    rlyid = ids[0].split(",")[0]
    resp = await bot.get_msg(message_id=rlyid)

    img_msg = str(resp['message'])

    rt = r"\[CQ:image,file=(.*?),subType=[\S]*,url=[\S]*\]"
    imgs = re.findall(rt, img_msg)

    if len(imgs) == 0:
        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + errMsg
        })
        await addtag.finish()


    flag, forward_index, inverted_index = addTag(tags, imgs[0], groupNum, forward_index, inverted_index)
    with open(plugin_config.inverted_index_path, 'w', encoding='UTF-8') as fc:
        json.dump(inverted_index, fc, indent=2, separators=(',',': '), ensure_ascii=False)

    if flag is None:
        msg = '该语录不存在'
    else:
        msg = '已为该语录添加上{}标签'.format(tags)

    await bot.call_api('send_group_msg', **{
        'group_id':int(groupNum),
        'message': '[CQ:at,qq='+user_id+']' + msg
    })

    await addtag.finish()


deltag = on_regex(pattern="^{}deltag\ ".format(plugin_config.quote_startcmd), **need_at)

@deltag.handle()
async def deltag_handle(bot: Bot, event: Event, state: T_State):

    global inverted_index
    global record_dict
    global forward_index

    session_id = event.get_session_id()
    user_id = str(event.get_user_id())
    tags = str(event.get_message()).replace('{}deltag'.format(plugin_config.quote_startcmd), '').strip().split(' ')

    if 'group' not in session_id:
        await addtag.finish()

    groupNum = session_id.split('_')[1]
    raw_message = str(event)

    errMsg = '请回复需要指定语录'

    rt = r"\[reply:id=(.*?)]"
    ids = re.findall(rt, str(raw_message))

    if len(ids) == 0:
        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + errMsg
        })
        await deltag.finish()

    rlyid = ids[0].split(",")[0]
    resp = await bot.get_msg(message_id=rlyid)

    img_msg = str(resp['message'])

    rt = r"\[CQ:image,file=(.*?),subType=[\S]*,url=[\S]*\]"
    imgs = re.findall(rt, img_msg)

    if len(imgs) == 0:
        await bot.call_api('send_group_msg', **{
            'group_id':int(groupNum),
            'message': '[CQ:at,qq='+user_id+']' + errMsg
        })
        await deltag.finish()


    flag, forward_index, inverted_index = delTag(tags, imgs[0], groupNum, forward_index, inverted_index)
    with open(plugin_config.inverted_index_path, 'w', encoding='UTF-8') as fc:
        json.dump(inverted_index, fc, indent=2, separators=(',',': '), ensure_ascii=False)

    if flag is None:
        msg = '该语录不存在'
    else:
        msg = '已移除该语录的{}标签'.format(tags)

    await bot.call_api('send_group_msg', **{
        'group_id':int(groupNum),
        'message': '[CQ:at,qq='+user_id+']' + msg
    })

    await deltag.finish()

