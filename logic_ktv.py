# -*- coding: utf-8 -*-
#########################################################
# python
import os, sys, traceback, re, json, threading, time, shutil
from datetime import datetime
# third-party
import requests
# third-party
from flask import request, render_template, jsonify, redirect, Response, send_file
from sqlalchemy import or_, and_, func, not_, desc
import lxml.html
from lxml import etree as ET

# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app
from framework.util import Util
from framework.common.util import headers, get_json_with_auth_session
from framework.common.plugin import LogicModuleBase, default_route_socketio
# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

from lib_metadata.server_util import MetadataServerUtil
#########################################################

class LogicKtv(LogicModuleBase):
    db_default = {
        'jav_ktv_db_version' : '1',
        'jav_ktv_daum_keyword' : u'나의 아저씨',
    }

    def __init__(self, P):
        super(LogicKtv, self).__init__(P, 'setting')
        self.name = 'ktv'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name

        try:
            return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)
        except:
            return render_template('sample.html', title='%s - %s' % (P.package_name, sub))

    def process_ajax(self, sub, req):
        try:
            if sub == 'test':
                keyword = req.form['keyword']
                call = req.form['call']
                if call == 'daum':
                    from lib_metadata import SiteDaumTv
                    ModelSetting.set('jav_ktv_daum_keyword', keyword)
                    ret = {}
                    ret['search'] = SiteDaumTv.search(keyword)
                return jsonify(ret)
        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    def process_api(self, sub, req):
        if sub == 'search':
            call = req.args.get('call')
            if call == 'plex':
                return jsonify(self.search(req.args.get('keyword')))
        elif sub == 'info':
            return jsonify(self.info(req.args.get('code')))

    #########################################################

    def search(self, keyword):
        ret = []
        #site_list = ModelSetting.get_list('jav_censored_order', ',')
        site_list = ['daum']
        for idx, site in enumerate(site_list):
            if site == 'daum':
                from lib_metadata import SiteDaumTv as SiteClass

            data = SiteClass.search(keyword)
            return data
            if data['ret'] == 'success':
                if idx != 0:
                    for item in data['data']:
                        item['score'] += -1
                ret += data['data']
                ret = sorted(ret, key=lambda k: k['score'], reverse=True)  
            if all_find:
                continue
            else:
                if len(ret) > 0 and ret[0]['score'] > 95:
                    break
        return ret
    

    def info(self, code):
        ret = None
        if ModelSetting.get_bool('jav_censored_use_sjva'):
            ret = MetadataServerUtil.get_metadata(code)
        if ret is None:
            if code[1] == 'B':
                from lib_metadata.site_javbus import SiteJavbus
                ret = self.info2(code, SiteJavbus)
            elif code[1] == 'D':
                from lib_metadata.site_dmm import SiteDmm
                ret = self.info2(code, SiteDmm)
        
        if ret is not None:
            ret['plex_is_proxy_preview'] = ModelSetting.get_bool('jav_censored_plex_is_proxy_preview')
            ret['plex_is_landscape_to_art'] = ModelSetting.get_bool('jav_censored_plex_landscape_to_art')
            ret['plex_art_count'] = ModelSetting.get_int('jav_censored_plex_art_count')

            if ret['actor'] is not None:
                for item in ret['actor']:
                    self.process_actor(item)

            ret['title'] = ModelSetting.get('jav_censored_title_format').format(
                originaltitle=ret['originaltitle'], 
                plot=ret['plot'],
                title=ret['title'],
                sorttitle=ret['sorttitle'],
                runtime=ret['runtime'],
                country=ret['country'],
                premiered=ret['premiered'],
                year=ret['year'],
                actor=ret['actor'][0]['name'] if ret['actor'] is not None and len(ret['actor']) > 0 else '',
                tagline=ret['tagline']
            )
            return ret

    def info2(self, code, SiteClass):
        image_mode = ModelSetting.get('jav_censored_{site_name}_image_mode'.format(site_name=SiteClass.site_name))
        data = SiteClass.info(
            code,
            proxy_url=ModelSetting.get('jav_censored_{site_name}_proxy_url'.format(site_name=SiteClass.site_name)) if ModelSetting.get_bool('jav_censored_{site_name}_use_proxy'.format(site_name=SiteClass.site_name)) else None, 
            image_mode=image_mode)
        if data['ret'] == 'success':
            ret = data['data']
            if ModelSetting.get_bool('jav_censored_use_sjva') and image_mode == '3' and SystemModelSetting.get('trans_type') == '1' and SystemModelSetting.get('trans_google_api_key') != '':
                MetadataServerUtil.set_metadata_jav_censored(code, ret, ret['title'].lower())
        return ret

    def process_actor(self, entity_actor):
        actor_site_list = ModelSetting.get_list('jav_censored_actor_order', ',')
        #logger.debug('actor_site_list : %s', actor_site_list)
        for site in actor_site_list:
            if site == 'hentaku':
                from lib_metadata.site_hentaku import SiteHentaku
                self.process_actor2(entity_actor, SiteHentaku, None)
            elif site == 'avdbs':
                from lib_metadata.site_avdbs import SiteAvdbs
                self.process_actor2(entity_actor, SiteAvdbs, ModelSetting.get('jav_censored_avdbs_proxy_url') if ModelSetting.get_bool('jav_censored_avdbs_use_proxy') else None)
            if entity_actor['name'] is not None:
                return
        if entity_actor['name'] is None:
            entity_actor['name'] = entity_actor['originalname'] 


    def process_actor2(self, entity_actor, SiteClass, proxy_url):
        
        if ModelSetting.get_bool('jav_censored_use_sjva'):
            #logger.debug('A' + SiteClass.site_char + entity_actor['originalname'])
            data = MetadataServerUtil.get_metadata('A' + SiteClass.site_char + entity_actor['originalname'])
            if data is not None and data['name'] is not None and data['name'] != '' and data['name'] != data['originalname'] and data['thumb'] is not None and data['thumb'].find('discordapp.net') != -1:
                logger.info('Get actor info by server : %s %s', entity_actor['originalname'], SiteClass)
                entity_actor['name'] = data['name']
                entity_actor['name2'] = data['name2']
                entity_actor['thumb'] = data['thumb']
                entity_actor['site'] = data['site']
                return
        #logger.debug('Get actor... :%s', SiteClass)
        SiteClass.get_actor_info(entity_actor, proxy_url=proxy_url)
        #logger.debug(entity_actor)
        if 'name' in entity_actor and entity_actor['name'] is not None and entity_actor['name'] != '' and 'thumb' in entity_actor and entity_actor['thumb'] is not None and entity_actor['thumb'].startswith('https://images-ext-'):
            MetadataServerUtil.set_metadata('A'+ SiteClass.site_char + entity_actor['originalname'], entity_actor, entity_actor['originalname'])
            return
        

