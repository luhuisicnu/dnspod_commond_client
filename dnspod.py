#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""旨在开发一个命令行工具，专用于dnspod.cn的域名记录管理.
0.1：初版
0.2：修改了配置文件的格式
0.3：增加token登录验证方式
1.0：调整功能架构，不仅仅是对记录进行修改，还应该有添加等功能
1.1：重构程序，使其面向对象，增加强制检查模式，发现不存在的记录则不执行任何修改
新增格式:
new = sub_domain1 record_type1 record_line1 value1 , sub_domain2 record_type2 record_line2 value2
修改格式（赋值）：
sub_domain1 record_type1 record_line1 value1 = sub_domain2 record_type2 record_line2 value2
__author__ = 'huil1@jumei.com'
__version__ = '1.1'
__lastupdate__ = '2016-08-03 11:00'"""

import warnings
import requests
import argparse
import configparser

DOMAIN_LIST_URL = 'https://dnsapi.cn/Domain.List'
RECORDS_LIST_URL = 'https://dnsapi.cn/Record.List'
RECORD_CREATE_URL = 'https://dnsapi.cn/Record.Create'
RECORD_MODIFY_URL = 'https://dnsapi.cn/Record.Modify'


class Config(configparser.ConfigParser):
    def get_domains(self):
        sections = self.sections()
        domains = [d for d in sections if '.' in d]
        return domains

    def str2record(self, record_str):
        record = {}
        if len(record_str.split()) < 3:
            print str(record_str.split())
            raise AttributeError('record must have at least 4 attribute:'
                                 'sub_domain,record_type,record_line,value')
        for index, attr in enumerate(record_str.split()):
            if index == 0:
                record['sub_domain'] = attr
            elif index == 1:
                record['record_type'] = attr.upper()
            elif index == 2:
                record['record_line'] = attr
            elif index == 3:
                record['value'] = attr
            else:
                try:
                    attr, value = attr.split(':')
                    record[attr] = value
                except Exception:
                    raise AttributeError('more than 4 attribute, '
                                         'format to "attr:value"')
        return record

    def get_domain_old_records(self, domain):
        return [self.str2record(record)
                for record in self.options(domain) if record != 'new']

    def _get_domain_old_records(self, domain):
        return [record for record in self.options(domain) if record != 'new']

    def get_domain_new_records(self, domain):
        return [self.str2record(self.get(domain, old_record))
                for old_record in self._get_domain_old_records(domain)]


class Domain(object):
    def __init__(self, id=None, name=None, conf=None):
        self.id = id
        self.name = name
        self.conf = conf
        self.token = conf.get('auth', 'login_token')
        self.section = conf[name]

    def get_dnspod_records(self, data_format='json'):
        data_dict = {
            'login_token': self.token,
            'domain_id': self.id,
            'format': data_format,
        }
        response = requests.post(RECORDS_LIST_URL, data=data_dict)
        data = response.json()
        if data['status']['code'] != '1':
            raise RuntimeError(
                'Error return code: {}'.format(data['status']['code']))
        return data['records']

    def create_records(self, data_format='json', show=True, enforce=True):
        '''
        enforce表示如果检查到已存在的记录，是否停止执行，show表示是否显示操作记录
        '''
        if not self.section.get('new'):
            raise RuntimeError('No such new record found in configfile')
        new_records = [self.conf.str2record(record.strip())
                       for record in self.section['new'].split(',')]
        exsit_records = self.get_dnspod_records()
        self.check_exist(new_records, exsit_records, enforce=enforce)
        for record in new_records:
            record['login_token'] = self.token
            record['format'] = data_format
            record['domain_id'] = self.id
            response = requests.post(RECORD_CREATE_URL, data=record)
            data = response.json()
            return_code = data['status']['code']
            if show:
                record.pop('login_token')
                record.pop('format')
                record.pop('domain_id')
                result_str = 'success' if return_code == '1' else 'failed'
                print 'new record:', str(record), result_str, return_code

    def is_exist(self, cfg_record, dnspod_records):
        '''
        检查一条配置文件中的记录，是否真实存在于dnspod上
        '''
        exist = False
        for record in dnspod_records:
            # 上传记录时关键字sub_domain,record_type,record_line,value。
            # 下载记录时关键字name,type,line,value。
            if cfg_record['sub_domain'] == record['name'] and\
                    cfg_record['record_type'] == record['type'] and\
                    cfg_record['record_line'] == record['line'] and\
                    cfg_record['value'] == record['value']:
                exist = record['id']
                break
        return exist

    def check_exist(self, new_records, exsit_records, enforce=True):
        '''
        enforce表示如果检查到已存在的记录，是否停止执行
        '''
        for record in new_records:
            if self.is_exist(record, exsit_records):
                exist_str = 'domain {}: new record {} '.\
                    format(self.name, str(record)) +\
                    'is already exist in dnspod'
                if enforce:
                    raise RuntimeError(exist_str)
                else:
                    warnings.warn(exist_str)

    def check_not_exist(self, old_records, exsit_records, enforce=True):
        '''
        enforce表示如果检查到 不存在!!! 的记录，是否停止执行
        '''
        for record in old_records:
            if not self.is_exist(record, exsit_records):
                exist_str = 'domain {}: old record {} '.\
                    format(self.name, str(record)) +\
                    'is not exist in dnspod'
                if enforce:
                    raise RuntimeError(exist_str)
                else:
                    warnings.warn(exist_str)

    def modify_records(self, data_format='json', show=True, enforce=True):
        exsit_records = self.get_dnspod_records()
        cfg_old_records = self.conf.get_domain_old_records(self.name)
        cfg_new_records = self.conf.get_domain_new_records(self.name)
        self.check_exist(cfg_new_records, exsit_records, enforce=enforce)
        self.check_not_exist(cfg_old_records, exsit_records, enforce=enforce)

        record_keys = [record for record in self.section if record != 'new']
        for key in record_keys:
            old_record = self.conf.str2record(key)
            new_record = self.conf.str2record(self.section[key])
            record_id = self.is_exist(old_record, exsit_records)
            # 原记录必须存在，新记录必须不存在
            # 到这一步证明是非强制检查模式，发现不合格的配置文件记录，直接忽略
            if record_id and not self.is_exist(new_record, exsit_records):
                new_record['login_token'] = self.token
                new_record['format'] = data_format
                new_record['domain_id'] = self.id
                new_record['record_id'] = record_id
                response = requests.post(RECORD_MODIFY_URL, data=new_record)
                data = response.json()
                return_code = data['status']['code']
                if show:
                    new_record.pop('login_token')
                    new_record.pop('format')
                    new_record.pop('domain_id')
                    new_record.pop('record_id')
                    result_str = 'success' if return_code == '1' else 'failed'
                    print 'modify record:', str(old_record), 'to',
                    print str(new_record), result_str, return_code

    def show_dnspod_records(self):
        for record in self.get_dnspod_records():
            print 'domain:', self.name,
            print 'name:', record['name'],
            print 'type:', record['type'],
            print 'line:', record['line'],
            print 'value:', record['value'],
            print 'status:', 'enable' if int(record['enabled']) else 'disable'

    def will_action(self, enforce=False):
        '''
        检查模式，检查即将进行的操作，而不实际执行
        '''
        exsit_records = self.get_dnspod_records()

        # 检查新增
        if self.section.get('new'):
            new_records = [self.conf.str2record(record.strip())
                           for record in self.section['new'].split(',')]
            self.check_exist(new_records, exsit_records, enforce=enforce)
            for record in new_records:
                if not self.is_exist(record, exsit_records):
                    print 'will create record:', str(record)

        # 检查修改
        cfg_old_records = self.conf.get_domain_old_records(self.name)
        cfg_new_records = self.conf.get_domain_new_records(self.name)
        self.check_exist(cfg_new_records, exsit_records, enforce=enforce)
        self.check_not_exist(cfg_old_records, exsit_records, enforce=enforce)

        record_keys = [record for record in self.section if record != 'new']
        for key in record_keys:
            old_record = self.conf.str2record(key)
            new_record = self.conf.str2record(self.section[key])
            record_id = self.is_exist(old_record, exsit_records)
            # 原记录必须存在，新记录必须不存在
            if record_id and not self.is_exist(new_record, exsit_records):
                print 'will modify record:', str(old_record),
                print 'to', str(new_record)


class DnsPod(object):
    def __init__(self, conf):
        self.conf = conf
        self.token = conf.get('auth', 'login_token')
        self.domains = self.get_dnspod_domains()
        self.check_domains()

    def get_dnspod_domains(self, data_format='json'):
        data_dict = {
            'login_token': self.token,
            'format': data_format
        }
        response = requests.post(DOMAIN_LIST_URL, data=data_dict)
        data = response.json()
        if data['status']['code'] != '1':
            raise RuntimeError(
                'Error return code: {}'.format(data['status']['code']))
        return [Domain(id=domain['id'], name=domain['name'], conf=self.conf)
                for domain in data['domains']]

    def show_dnspod_domains(self):
        for domain in self.domains:
            print 'id:', domain.id, 'name:', domain.name

    def show_dnspod_domains_records(self):
        for domain in self.domains:
            domain.show_dnspod_records()

    def check_domains(self):
        dns_domains = [domain.name for domain in self.domains]
        for cfg_domain in self.conf.get_domains():
            if cfg_domain not in dns_domains:
                raise RuntimeError(
                    'Error on cfg file: No such domain {dm} on dnspod.cn'
                    .format(dm=domain))


def init_parser():
    parser = argparse.ArgumentParser(description='DnsPod Client version: 1.1')
    parser.add_argument(dest='configfile', metavar='configfile',
                        action='store')
    parser.add_argument('-d', '--show-domains', dest='show_domains',
                        action='store_true', help='show all domains in dnspod')
    parser.add_argument('-r', '--show-records', dest='show_records',
                        action='store_true', help='show all records in dnspod')
    parser.add_argument('-c', '--check-action', dest='check_action',
                        action='store_true',
                        help='check what will action with the configfile')
    parser.add_argument('-n', '--new-records', dest='new',
                        action='store_true',
                        help='create records in configfile but not in dnspod')
    parser.add_argument('-m', '--modify-records', dest='modify',
                        action='store_true',
                        help='modify records in configfile, which old_record'
                        ' in dnspod but new_record not in dnspod')
    parser.add_argument('-a', '--all-action', dest='newAndModify',
                        action='store_true',
                        help='create and modify if them exist')
    return parser


def main():
    # 命令行参数处理
    parser = init_parser()
    args = parser.parse_args()
    if args.show_domains + args.show_records + args.check_action + args.new +\
            args.modify + args.newAndModify != 1:
        raise RuntimeError('Error on arguments: -d, -r, -c, -n, -m, -a'
                           ' only one of them allowed once')
    # 获取配置文件后，初始化dnspod实例
    config = Config()
    config.read(unicode(args.configfile))
    dnspod = DnsPod(config)
    # 根据命令行参数，执行dnspod实例的操作
    if args.show_domains:
        dnspod.show_dnspod_domains()
    elif args.show_records:
        dnspod.show_dnspod_domains_records()
    elif args.check_action:
        for domain in dnspod.domains:
            domain.will_action()
    elif args.new:
        for domain in dnspod.domains:
            domain.create_records()
    elif args.modify:
        for domain in dnspod.domains:
            domain.modify_records()
    elif args.newAndModify:
        for domain in dnspod.domains:
            if domain.section.get('new'):
                domain.create_records()
                domain.section.pop('new')
            if domain.section:
                domain.modify_records()


if __name__ == "__main__":
    main()
