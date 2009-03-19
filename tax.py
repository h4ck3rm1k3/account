#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
"Tax"
from trytond.model import ModelView, ModelSQL, fields
from trytond.wizard import Wizard
from decimal import Decimal
from trytond.tools import Cache


class Group(ModelSQL, ModelView):
    'Tax Group'
    _name = 'account.tax.group'
    _description = __doc__

    name = fields.Char('Name', size=None, required=True, translate=True)
    code = fields.Char('Code', size=None, required=True)

    def __init__(self):
        super(Group, self).__init__()
        self._sql_constraints += [
            ('code_uniq', 'UNIQUE(code)', 'Code must be unique!'),
        ]

Group()


class CodeTemplate(ModelSQL, ModelView):
    'Tax Code Template'
    _name = 'account.tax.code.template'
    _description = __doc__

    name = fields.Char('Name', required=True)
    code = fields.Char('Code')
    parent = fields.Many2One('account.tax.code.template', 'Parent')
    childs = fields.One2Many('account.tax.code.template', 'parent', 'Children')
    account = fields.Many2One('account.account.template', 'Account Template',
            domain=[('parent', '=', False)], required=True)

    def __init__(self):
        super(CodeTemplate, self).__init__()
        self._constraints += [
            ('check_recursion', 'recursive_tax_code'),
        ]
        self._error_messages.update({
            'recursive_tax_code': 'You can not create recursive tax code!',
        })
        self._order.insert(0, ('code', 'ASC'))
        self._order.insert(0, ('account', 'ASC'))

    def _get_tax_code_value(self, cursor, user, template, context=None):
        '''
        Set values for tax code creation.

        :param cursor: the database cursor
        :param user: the user id
        :param template: the BrowseRecord of the template
        :param context: the context
        :return: a dictionary with account fields as key and values as value
        '''
        res = {}
        res['name'] = template.name
        res['code'] = template.code
        res['template'] = template.id
        return res

    def create_tax_code(self, cursor, user, template, company_id, context=None,
            template2tax_code=None, parent_id=False):
        '''
        Create recursively tax codes based on template.

        :param cursor: the database cursor
        :param user: the user id
        :param template: the template id or the BrowseRecord of template
                used for tax code creation
        :param company_id: the id of the company for which tax codes are
                created
        :param context: the context
        :param template2tax_code: a dictionary with tax code template id as key
                and tax code id as value, used to convert template id into
                tax code. The dictionary is filled with new tax codes
        :param parent_id: the tax code id of the parent of the tax codes that
                must be created
        :return: id of the tax code created
        '''
        tax_code_obj = self.pool.get('account.tax.code')

        if template2tax_code is None:
            template2tax_code = {}

        if isinstance(template, (int, long)):
            template = self.browse(cursor, user, template, context=context)

        if template.id not in template2tax_code:
            vals = self._get_tax_code_value(cursor, user, template,
                    context=context)
            vals['company'] = company_id
            vals['parent'] = parent_id

            new_id = tax_code_obj.create(cursor, user, vals, context=context)
            template2tax_code[template.id] = new_id
        else:
            new_id = template2tax_code[template.id]

        new_childs = []
        for child in template.childs:
            new_childs.append(self.create_tax_code(cursor, user, child,
                company_id, context=context,
                template2tax_code=template2tax_code, parent_id=new_id))
        return new_id

CodeTemplate()


class Code(ModelSQL, ModelView):
    'Tax Code'
    _name = 'account.tax.code'
    _description = __doc__

    name = fields.Char('Name', size=None, required=True, select=1)
    code = fields.Char('Code', size=None, select=1)
    active = fields.Boolean('Active', select=2)
    company = fields.Many2One('company.company', 'Company', required=True)
    parent = fields.Many2One('account.tax.code', 'Parent', select=1,
            domain="[('company', '=', company)]", depends=['company'])
    childs = fields.One2Many('account.tax.code', 'parent', 'Children',
            domain="[('company', '=', company)]", depends=['company'])
    currency_digits = fields.Function('get_currency_digits', type='integer',
            string='Currency Digits', on_change_with=['company'])
    sum = fields.Function('get_sum', digits="(16, currency_digits)",
            string='Sum', depends=['currency_digits'])
    template = fields.Many2One('account.tax.code.template', 'Template')

    def __init__(self):
        super(Code, self).__init__()
        self._constraints += [
            ('check_recursion', 'recursive_tax_code'),
        ]
        self._error_messages.update({
            'recursive_tax_code': 'You can not create recursive tax code!',
        })
        self._order.insert(0, ('code', 'ASC'))

    def default_active(self, cursor, user, context=None):
        return True

    def default_company(self, cursor, user, context=None):
        company_obj = self.pool.get('company.company')
        if context is None:
            context = {}
        if context.get('company'):
            return context['company']
        return False

    def on_change_with_currency_digits(self, cursor, user, ids, vals,
            context=None):
        company_obj = self.pool.get('company.company')
        if vals.get('company'):
            company = company_obj.browse(cursor, user, vals['company'],
                    context=context)
            return company.currency.digits
        return 2

    def get_currency_digits(self, cursor, user, ids, name, arg, context=None):
        res = {}
        for code in self.browse(cursor, user, ids, context=context):
            res[code.id] = code.company.currency.digits
        return res

    def get_sum(self, cursor, user, ids, name, arg, context=None):
        res = {}
        move_line_obj = self.pool.get('account.move.line')
        currency_obj = self.pool.get('currency.currency')

        child_ids = self.search(cursor, user, [('parent', 'child_of', ids)],
                context=context)
        all_ids = {}.fromkeys(ids + child_ids).keys()
        line_query, _ = move_line_obj.query_get(cursor, user, context=context)
        cursor.execute('SELECT c.id, ' \
                    'SUM(tl.amount) ' \
                'FROM account_tax_code c, ' \
                    'account_tax_line tl, ' \
                    'account_move_line l ' \
                'WHERE c.id = tl.code ' \
                    'AND tl.move_line = l.id ' \
                    'AND c.id IN (' + \
                        ','.join(['%s' for x in all_ids])+ ') ' \
                    'AND ' + line_query + ' ' \
                    'AND c.active ' \
                'GROUP BY c.id', all_ids)
        code_sum = {}
        for code_id, sum in cursor.fetchall():
            code_sum[code_id] = sum

        for code in self.browse(cursor, user, ids, context=context):
            res.setdefault(code.id, Decimal('0.0'))
            child_ids = self.search(cursor, user, [
                ('parent', 'child_of', [code.id]),
                ], context=context)
            for child_id in child_ids:
                res[code.id] += currency_obj.round(cursor, user,
                        code.company.currency,
                        code_sum.get(child_id, Decimal('0.0')))
            res[code.id] = currency_obj.round(cursor, user,
                    code.company.currency, res[code.id])
        return res

    def get_rec_name(self, cursor, user, ids, name, arg, context=None):
        if not ids:
            return {}
        res = {}
        for code in self.browse(cursor, user, ids, context=context):
            if code.code:
                res[code.id] = code.code + ' - ' + code.name
            else:
                res[code.id] = code.name
        return res

    def search_rec_name(self, cursor, user, name, args, context=None):
        args2 = []
        i = 0
        while i < len(args):
            ids = self.search(cursor, user, [('code', args[i][1], args[i][2])],
                    context=context)
            if ids:
                args2.append(('code', args[i][1], args[i][2]))
            else:
                args2.append(('name', args[i][1], args[i][2]))
            i += 1
        return args2

    def delete(self, cursor, user, ids, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        code_ids = self.search(cursor, user, [
            ('parent', 'child_of', ids),
            ], context=context)
        return super(Code, self).delete(cursor, user, code_ids,
                context=context)

    def update_tax_code(self, cursor, user, code, context=None,
            template2tax_code=None):
        '''
        Update recursively tax code based on template.

        :param cursor: the database cursor
        :param user: the user id
        :param code: a code id or the BrowseRecord of the code
        :param context: the context
        :param template2tax_code: a dictionary with tax code template id as key
                and tax code id as value, used to convert template id into
                tax code. The dictionary is filled with new tax codes
        '''
        template_obj = self.pool.get('account.tax.code.template')

        if template2tax_code is None:
            template2tax_code = {}

        if isinstance(code, (int, long)):
            code = self.browse(cursor, user, code, context=context)

        if code.template:
            vals = template_obj._get_tax_code_value(cursor, user,
                    code.template, context=context)
            self.write(cursor, user, code.id, vals, context=context)
            template2tax_code[code.template.id] = code.id

        for child in code.childs:
            self.update_tax_code(cursor, user, child, context=context,
                    template2tax_code=template2tax_code)

Code()


class OpenChartCodeInit(ModelView):
    'Open Chart Code Init'
    _name = 'account.tax.open_chart_code.init'
    _description = __doc__
    method = fields.Selection([
        ('fiscalyear', 'By Fiscal Year'),
        ('periods', 'By Periods'),
        ], 'Method', required=True)
    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
            help='Keep empty for all open fiscal year',
            states={
                'invisible': "method != 'fiscalyear'",
            }, depends=['method'])
    periods = fields.Many2Many('account.period', None, None, 'Periods',
            help='Keep empty for all periods of all open fiscal year',
            states={
                'invisible': "method != 'periods'",
            }, depends=['method'])

    def default_method(self, cursor, user, context=None):
        return 'periods'

OpenChartCodeInit()


class OpenChartCode(Wizard):
    'Open Chart Of Tax Code by Fiscal Year'
    _name = 'account.tax.open_chart_code'
    states = {
        'init': {
            'result': {
                'type': 'form',
                'object': 'account.tax.open_chart_code.init',
                'state': [
                    ('end', 'Cancel', 'tryton-cancel'),
                    ('open', 'Open', 'tryton-ok', True),
                ],
            },
        },
        'open': {
            'result': {
                'type': 'action',
                'action': '_action_open_chart',
                'state': 'end',
            },
        },
    }

    def _action_open_chart(self, cursor, user, data, context=None):
        model_data_obj = self.pool.get('ir.model.data')
        act_window_obj = self.pool.get('ir.action.act_window')

        model_data_ids = model_data_obj.search(cursor, user, [
            ('fs_id', '=', 'act_tax_code_tree2'),
            ('module', '=', 'account'),
            ('inherit', '=', False),
            ], limit=1, context=context)
        model_data = model_data_obj.browse(cursor, user, model_data_ids[0],
                context=context)
        res = act_window_obj.read(cursor, user, model_data.db_id,
                context=context)
        if data['form']['method'] == 'fiscalyear':
            res['context'] = str({'fiscalyear': data['form']['fiscalyear']})
        else:
            res['context'] = str({'periods': data['form']['periods'][0][1]})
        return res

OpenChartCode()


class TaxTemplate(ModelSQL, ModelView):
    'Account Tax Template'
    _name = 'account.tax.template'
    _description = __doc__

    name = fields.Char('Name', required=True, translate=True)
    description = fields.Char('Description', required=True, translate=True)
    group = fields.Many2One('account.tax.group', 'Group', required=True)
    sequence = fields.Integer('Sequence')
    amount = fields.Numeric('Amount', digits=(16, 2))
    percentage = fields.Numeric('Percentage', digits=(16, 8))
    type = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed'),
        ('none', 'None'),
        ], 'Type', required=True)
    parent = fields.Many2One('account.tax.template', 'Parent')
    childs = fields.One2Many('account.tax.template', 'parent', 'Children')
    invoice_account = fields.Many2One('account.account.template',
            'Invoice Account')
    credit_note_account = fields.Many2One('account.account.template',
            'Credit Note Account')
    invoice_base_code = fields.Many2One('account.tax.code.template',
            'Invoice Base Code')
    invoice_base_sign = fields.Numeric('Invoice Base Sign', digits=(2, 0))
    invoice_tax_code = fields.Many2One('account.tax.code.template',
            'Invoice Tax Code')
    invoice_tax_sign = fields.Numeric('Invoice Tax Sign', digits=(2, 0))
    credit_note_base_code = fields.Many2One('account.tax.code.template',
            'Credit Note Base Code')
    credit_note_base_sign = fields.Numeric('Credit Note Base Sign', digits=(2, 0))
    credit_note_tax_code = fields.Many2One('account.tax.code.template',
            'Credit Note Tax Code')
    credit_note_tax_sign = fields.Numeric('Credit Note Tax Sign', digits=(2, 0))
    account = fields.Many2One('account.account.template', 'Account Template',
            domain=[('parent', '=', False)], required=True)

    def __init__(self):
        super(TaxTemplate, self).__init__()
        self._order.insert(0, ('sequence', 'ASC'))
        self._order.insert(0, ('account', 'ASC'))

    def default_group(self, cursor, user, context=None):
        group_obj = self.pool.get('account.tax.group')
        group_ids = group_obj.search(cursor, user, [
            ('code', '=', 'none'),
            ], limit=1, context=context)
        return group_ids[0]

    def default_type(self, cursor, user, context=None):
        return 'percentage'

    def default_include_base_amount(self, cursor, user, context=None):
        return False

    def default_invoice_base_sign(self, cursor, user, context=None):
        return 1

    def default_invoice_tax_sign(self, cursor, user, context=None):
        return 1

    def default_credit_note_base_sign(self, cursor, user, context=None):
        return 1

    def default_credit_note_tax_sign(self, cursor, user, context=None):
        return 1

    def _get_tax_value(self, cursor, user, template, context=None):
        '''
        Set values for tax creation.

        :param cursor: the database cursor
        :param user: the user id
        :param template: the BrowseRecord of the template
        :param context: the context
        :return: a dictionary with account fields as key and values as value
        '''
        res = {}
        for field in ('name', 'description', 'sequence', 'amount',
                'percentage', 'type', 'invoice_base_sign', 'invoice_tax_sign',
                'credit_note_base_sign', 'credit_note_tax_sign'):
            res[field] = template[field]
        for field in ('group',):
            res[field] = template[field].id
        res['template'] = template.id
        return res

    def create_tax(self, cursor, user, template, company_id,
            template2tax_code, template2account, context=None,
            template2tax=None, parent_id=False):
        '''
        Create recursively taxes based on template.

        :param cursor: the database cursor
        :param user: the user id
        :param template: the template id or the BrowseRecord of template
                used for tax creation
        :param company_id: the id of the company for which taxes are created
        :param template2tax_code: a dictionary with tax code template id as key
                and tax code id as value, used to convert tax code template into
                tax code
        :param template2account: a dictionary with account template id as key
                and account id as value, used to convert account template into
                account code
        :param context: the context
        :param template2tax: a dictionary with tax template id as key and
                tax id as value, used to convert template id into tax.
                The dictionary is filled with new taxes
        :param parent_id: the tax id of the parent of the tax that must be
                created
        :return: id of the tax created
        '''
        tax_obj = self.pool.get('account.tax')

        if template2tax is None:
            template2tax = {}

        if isinstance(template, (int, long)):
            template = self.browse(cursor, user, template, context=context)

        if template.id not in template2tax:
            vals = self._get_tax_value(cursor, user, template, context=context)
            vals['company'] = company_id
            vals['parent'] = parent_id
            if template.invoice_account:
                vals['invoice_account'] = \
                        template2account[template.invoice_account.id]
            else:
                vals['invoice_account'] =  False
            if template.credit_note_account:
                vals['credit_note_account'] = \
                        template2account[template.credit_note_account.id]
            else:
                vals['credit_note_account'] = False
            if template.invoice_base_code:
                vals['invoice_base_code'] = \
                        template2tax_code[template.invoice_base_code.id]
            else:
                vals['invoice_base_code'] = False
            if template.invoice_tax_code:
                vals['invoice_tax_code'] = \
                        template2tax_code[template.invoice_tax_code.id]
            else:
                vals['invoice_tax_code'] = False
            if template.credit_note_base_code:
                vals['credit_note_base_code'] = \
                        template2tax_code[template.credit_note_base_code.id]
            else:
                vals['credit_note_base_code'] = False
            if template.credit_note_tax_code:
                vals['credit_note_tax_code'] = \
                        template2tax_code[template.credit_note_tax_code.id]
            else:
                vals['credit_note_tax_code'] = False

            new_id = tax_obj.create(cursor, user, vals, context=context)
            template2tax[template.id] = new_id
        else:
            new_id = template2tax[template.id]

        new_childs = []
        for child in template.childs:
            new_childs.append(self.create_tax(cursor, user, child,
                company_id, template2tax_code, template2account, 
                context=context, template2tax=template2tax, parent_id=new_id))
        return new_id

TaxTemplate()


class Tax(ModelSQL, ModelView):
    '''
    Account Tax

    Type:
        percentage: tax = price * amount
        fixed: tax = amount
        none: tax = none
    '''
    _name = 'account.tax'
    _description = 'Account Tax'

    name = fields.Char('Name', required=True, translate=True)
    description = fields.Char('Description', required=True, translate=True,
            help="The name that will be used in reports")
    group = fields.Many2One('account.tax.group', 'Group', required=True,
            states={
                'invisible': "locals().get('parent', True)",
            }, depends=['parent'])
    active = fields.Boolean('Active')
    sequence = fields.Integer('Sequence',
            help='Use to order the taxes')
    amount = fields.Numeric('Amount', digits=(16, 2),
            states={
                'invisible': "type != 'fixed'",
            }, help='In company\'s currency', depends=['type'])
    percentage = fields.Numeric('Percentage', digits=(16, 8),
            states={
                'invisible': "type != 'percentage'",
            }, help='In %', depends=['type'])
    type = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed'),
        ('none', 'None'),
        ], 'Type', required=True)
    parent = fields.Many2One('account.tax', 'Parent', ondelete='CASCADE')
    childs = fields.One2Many('account.tax', 'parent', 'Children')
    company = fields.Many2One('company.company', 'Company', required=True)
    invoice_account = fields.Many2One('account.account', 'Invoice Account',
            domain="[('company', '=', company)]",
            help='Keep empty to use the default invoice account',
            states={
                'readonly': "type == 'none' or not company",
                'required': "type != 'none' and company",
            }, depends=['company'])
    credit_note_account = fields.Many2One('account.account', 'Credit Note Account',
            domain="[('company', '=', company)]",
            help='Keep empty to use the default credit_note account',
            states={
                'readonly': "type == 'none' or not company",
                'required': "type != 'none' and company",
            }, depends=['company', 'type'])

    invoice_base_code = fields.Many2One('account.tax.code',
            'Invoice Base Code',
            states={
                'readonly': "type == 'none'",
            }, depends=['type'])
    invoice_base_sign = fields.Numeric('Invoice Base Sign', digits=(2, 0),
            help='Usualy 1 or -1',
            states={
                'readonly': "type == 'none'",
            }, depends=['type'])
    invoice_tax_code = fields.Many2One('account.tax.code',
            'Invoice Tax Code',
            states={
                'readonly': "type == 'none'",
            }, depends=['type'])
    invoice_tax_sign = fields.Numeric('Invoice Tax Sign', digits=(2, 0),
            help='Usualy 1 or -1',
            states={
                'readonly': "type == 'none'",
            }, depends=['type'])
    credit_note_base_code = fields.Many2One('account.tax.code',
            'Credit Note Base Code',
            states={
                'readonly': "type == 'none'",
            }, depends=['type'])
    credit_note_base_sign = fields.Numeric('Credit Note Base Sign', digits=(2, 0),
            help='Usualy 1 or -1',
            states={
                'readonly': "type == 'none'",
            }, depends=['type'])
    credit_note_tax_code = fields.Many2One('account.tax.code',
            'Credit Note Tax Code',
            states={
                'readonly': "type == 'none'",
            }, depends=['type'])
    credit_note_tax_sign = fields.Numeric('Credit Note Tax Sign', digits=(2, 0),
            help='Usualy 1 or -1',
            states={
                'readonly': "type == 'none'",
            }, depends=['type'])
    template = fields.Many2One('account.tax.template', 'Template')

    def __init__(self):
        super(Tax, self).__init__()
        self._order.insert(0, ('sequence', 'ASC'))

    def default_active(self, cursor, user, context=None):
        return True

    def default_group(self, cursor, user, context=None):
        group_obj = self.pool.get('account.tax.group')
        group_ids = group_obj.search(cursor, user, [
            ('code', '=', 'none'),
            ], limit=1, context=context)
        return group_ids[0]

    def default_type(self, cursor, user, context=None):
        return 'percentage'

    def default_include_base_amount(self, cursor, user, context=None):
        return False

    def default_invoice_base_sign(self, cursor, user, context=None):
        return 1

    def default_invoice_tax_sign(self, cursor, user, context=None):
        return 1

    def default_credit_note_base_sign(self, cursor, user, context=None):
        return 1

    def default_credit_note_tax_sign(self, cursor, user, context=None):
        return 1

    def default_company(self, cursor, user, context=None):
        company_obj = self.pool.get('company.company')
        if context is None:
            context = {}
        if context.get('company'):
            return context['company']
        return False

    def _process_tax(self, cursor, user, tax, price_unit, context=None):
        if tax.type == 'percentage':
            amount = price_unit * tax.percentage / Decimal('100')
            return {
                'base': price_unit,
                'amount': amount,
                'tax': tax,
            }
        if tax.type == 'fixed':
            amount = tax.amount
            return {
                'base': price_unit,
                'amount': amount,
                'tax': tax,
            }

    def _unit_compute(self, cursor, user, taxes, price_unit, context=None):
        res = []
        for tax in taxes:
            if tax.type != 'none':
                res.append(self._process_tax(cursor, user, tax, price_unit,
                    context=context))
            if len(tax.childs):
                res.extend(self._unit_compute(cursor, user, tax.childs,
                    price_unit, context=context))
        return res

    def delete(self, cursor, user, ids, context=None):
        # Restart the cache
        self.sort_taxes(cursor.dbname)
        return super(Tax, self).delete(cursor, user, ids, context=context)

    def create(self, cursor, user, vals, context=None):
        # Restart the cache
        self.sort_taxes(cursor.dbname)
        return super(Tax, self).create(cursor, user, vals, context=context)

    def write(self, cursor, user, ids, vals, context=None):
        # Restart the cache
        self.sort_taxes(cursor.dbname)
        return super(Tax, self).write(cursor, user, ids, vals, context=context)

    def sort_taxes(self, cursor, user, ids, context=None):
        '''
        Return a list of taxe ids sorted

        :param cursor: the database cursor
        :param user: the user id
        :param ids: a list of tax ids
        :param context: the context
        :return: a list of tax ids sorted
        '''
        return self.search(cursor, user, [
            ('id', 'in', ids),
            ], order=[('sequence', 'ASC'), ('id', 'ASC')], context=context)

    sort_taxes = Cache('account_tax.sort_taxes')(sort_taxes)

    def compute(self, cursor, user, ids, price_unit, quantity, context=None):
        '''
        Compute taxes for price_unit and quantity.
        Return list of dict for each taxes and their childs with:
            base
            amount
            tax
        '''
        ids = self.sort_taxes(cursor, user, ids, context=context)
        taxes = self.browse(cursor, user, ids, context=context)
        res = self._unit_compute(cursor, user, taxes, price_unit,
                context=context)
        quantity = Decimal(str(quantity or 0.0))
        for row in res:
            row['base'] *= quantity
            row['amount'] *= quantity
        return res

    def _process_tax_inv(self, cursor, user, tax, price_unit, context=None):
        # base will be calculate when all taxes will be compute
        if tax.type == 'percentage':
            amount = price_unit - (price_unit / \
                    (1 + (tax.percentage / Decimal('100'))))
            return {
                'base': price_unit,
                'amount': amount,
                'tax': tax,
            }
        if tax.type == 'fixed':
            amount = tax.amount
            return {
                'base': price_unit,
                'amount': amount,
                'tax': tax,
            }

    def _unit_compute_inv(self, cursor, user, taxes, price_unit, context=None):
        res = []
        total_amount = Decimal('0.0')
        for tax in taxes:
            if tax.type != 'none':
                res.append(self._process_tax_inv(cursor, user, tax, price_unit,
                    context=context))
                total_amount += res[-1]['amount']
            if len(tax.childs):
                tax.childs.reverse()
                res_childs = self._unit_compute_inv(cursor, user, tax.childs,
                    price_unit, context=context)
                for res_child in res_childs:
                    total_amount += res_child['amount']
                res.extend(res_childs)
        for row in res:
            row['base'] -= total_amount
        return res

    def compute_inv(self, cursor, user, ids, price_unit, quantity,
            context=None):
        '''
        Compute the inverse taxes for price_unit and quantity.
        Return list of dict for each taxes and their childs with:
            base
            amount
            tax
        '''
        ids = self.sort_taxes(cursor, user, ids, context=context)
        taxes = self.browse(cursor, user, ids, context=context)
        taxes.reverse()
        res = self._unit_compute_inv(cursor, user, taxes, price_unit,
                context=context)
        res.reverse()
        quantity = Decimal(str(quantity or 0.0))
        for row in res:
            row['base'] *= quantity
            row['amount'] *= quantity
        return res

    def update_tax(self, cursor, user, tax, template2tax_code,
            template2account, context=None, template2tax=None):
        '''
        Update recursively taxes based on template.

        :param cursor: the database cursor
        :param user: the user id
        :param tax: a tax id or the BrowseRecord of the tax
        :param template2tax_code: a dictionary with tax code template id as key
                and tax code id as value, used to convert tax code template into
                tax code
        :param template2account: a dictionary with account template id as key
                and account id as value, used to convert account template into
                account code
        :param context: the context
        :param template2tax: a dictionary with tax template id as key and
                tax id as value, used to convert template id into tax.
                The dictionary is filled with new taxes
        '''
        template_obj = self.pool.get('account.tax.template')

        if template2tax is None:
            template2tax = {}

        if isinstance(tax, (int, long)):
            tax = self.browse(cursor, user, tax, context=context)

        if tax.template:
            vals = template_obj._get_tax_value(cursor, user, tax.template,
                    context=context)
            if tax.template.invoice_account:
                vals['invoice_account'] = \
                        template2account.get(tax.template.invoice_account.id,
                                False)
            else:
                vals['invoice_account'] =  False
            if tax.template.credit_note_account:
                vals['credit_note_account'] = \
                        template2account.get(tax.template.credit_note_account.id,
                                False)
            else:
                vals['credit_note_account'] = False
            if tax.template.invoice_base_code:
                vals['invoice_base_code'] = \
                        template2tax_code.get(tax.template.invoice_base_code.id,
                                False)
            else:
                vals['invoice_base_code'] = False
            if tax.template.invoice_tax_code:
                vals['invoice_tax_code'] = \
                        template2tax_code.get(tax.template.invoice_tax_code.id,
                                False)
            else:
                vals['invoice_tax_code'] = False
            if tax.template.credit_note_base_code:
                vals['credit_note_base_code'] = \
                        template2tax_code.get(tax.template.credit_note_base_code.id,
                                False)
            else:
                vals['credit_note_base_code'] = False
            if tax.template.credit_note_tax_code:
                vals['credit_note_tax_code'] = \
                        template2tax_code.get(tax.template.credit_note_tax_code.id,
                                False)
            else:
                vals['credit_note_tax_code'] = False

            self.write(cursor, user, tax.id, vals, context=context)
            template2tax[tax.template.id] = tax.id

        for child in tax.childs:
            self.update_tax(cursor, user, tax, context=context)

Tax()


class Line(ModelSQL, ModelView):
    'Tax Line'
    _name = 'account.tax.line'
    _description = __doc__
    _rec_name = 'amount'

    amount = fields.Numeric('Amount', digits=(16, 2))
    code = fields.Many2One('account.tax.code', 'Code', select=1, required=True)
    move_line = fields.Many2One('account.move.line', 'Move Line',
            required=True, select=1, ondelete='CASCADE')

Line()


class OpenCode(Wizard):
    'Open Code'
    _name = 'account.tax.open_code'
    states = {
        'init': {
            'result': {
                'type': 'action',
                'action': '_action_open_code',
                'state': 'end',
            },
        },
    }

    def _action_open_code(self, cursor, user, data, context=None):
        if context is None:
            context = {}
        model_data_obj = self.pool.get('ir.model.data')
        act_window_obj = self.pool.get('ir.action.act_window')
        fiscalyear_obj = self.pool.get('account.fiscalyear')
        period_obj = self.pool.get('account.period')

        if not context.get('fiscalyear'):
            fiscalyear_ids = fiscalyear_obj.search(cursor, user, [
                ('state', '=', 'open'),
                ], context=context)
        else:
            fiscalyear_ids = [context['fiscalyear']]

        period_ids = []
        if not context.get('periods'):
            period_ids = period_obj.search(cursor, user, [
                ('fiscalyear', 'in', fiscalyear_ids),
                ], context=context)
        else:
            period_ids = context['periods']

        model_data_ids = model_data_obj.search(cursor, user, [
            ('fs_id', '=', 'act_tax_line_form'),
            ('module', '=', 'account'),
            ('inherit', '=', False),
            ], limit=1, context=context)
        model_data = model_data_obj.browse(cursor, user, model_data_ids[0],
                context=context)
        res = act_window_obj.read(cursor, user, model_data.db_id,
                context=context)
        res['domain'] = str([
            ('move_line.period', 'in', period_ids),
            ('code', '=', data['id']),
            ])
        if context.get('fiscalyear'):
            res['context'] = str({'fiscalyear': context['fiscalyear']})
        else:
            res['context'] = str({'periods': period_ids})
        return res

OpenCode()


class AccountTemplateTaxTemplate(ModelSQL):
    'Account Template - Tax Template'
    _name = 'account.account.template-account.tax.template'
    _table = 'account_account_template_tax_rel'
    _description = __doc__
    account = fields.Many2One('account.account.template', 'Account Template',
            ondelete='CASCADE', select=1, required=True)
    tax = fields.Many2One('account.tax.template', 'Tax Template',
            ondelete='RESTRICT', select=1, required=True)

AccountTemplateTaxTemplate()


class AccountTemplate(ModelSQL, ModelView):
    _name = 'account.account.template'
    taxes = fields.Many2Many('account.account.template-account.tax.template',
            'account', 'tax', 'Default Taxes',
            domain="[('parent', '=', False)]")

AccountTemplate()


class AccountTax(ModelSQL):
    _name = 'account.account-account.tax'
    _table = 'account_account_tax_rel'
    account = fields.Many2One('account.account', 'Account', ondelete='CASCADE',
            select=1, required=True)
    tax = fields.Many2One('account.tax', 'Tax', ondelete='RESTRICT',
            select=1, required=True)

AccountTax()


class Account(ModelSQL, ModelView):
    _name = 'account.account'
    taxes = fields.Many2Many('account.account-account.tax',
            'account', 'tax', 'Default Taxes',
            domain="[('company', '=', company), ('parent', '=', False)]",
            help='Default tax for manual encoding move lines \n' \
                    'for journal type: "expense" and "revenue"',
            depends=['company'])

Account()
