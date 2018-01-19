# encoding: UTF-8

from odoo import models, fields, api
from odoo.addons.ud_reserva.models import utils
from odoo.exceptions import ValidationError


class Reserva(models.Model):
    """
    Descrição: Objeto responsável por armazenar os metadados e a lista de dias (obj) que a reserva possui
    Name: ud.reserva
    """
    _name = 'ud.reserva'

    _order = 'data_solicitacao desc'

    name = fields.Char(u'Nome', compute='get_name')
    solicitante_id = fields.Many2one('res.users', string=u'Solicitante', required=True,
                                     default=lambda self: self.env.uid)
    titulo = fields.Char(u'Nome do evento', required=True)
    descricao = fields.Text(u'Descrição do evento')
    data_solicitacao = fields.Datetime(u'Data da solicitação', default=fields.datetime.now())
    state = fields.Selection(utils.STATUS_RESERVA, u'Status', default='nova')
    dia_ids = fields.One2many('ud.reserva.dia', 'reserva_id', u'Dias', ondelete='cascade')
    espaco_aprovado_ids = fields.Many2many('ud.espaco', 'reserva_espaco_aprovado_rel', string=u'Espaços aprovados')
    motivo_cancelamento = fields.Text(u'Motivo de cancelamento')
    data_cancelamento = fields.Datetime(u'Data/hora de cancelamento')

    @api.one
    def get_name(self):
        self.name = u'{}'.format(self.titulo)

    def filtra_responsavel(self):
        """
        Usado para filtrar de acordo com parâmetros passados no XML através do campo context
        :return:
        """
        domain = []
        if self.env.context.get('filtrar_responsavel'):
            espaco_ids = [espaco.id for espaco in self.espacos_responsavel()]
            domain.append(('dia_ids.espaco_id', 'in', espaco_ids))
        if self.env.context.get('filtrar_solicitante'):
            domain.append(('solicitante_id', '=', self.env.uid))
        return domain

    def read(self, fields=None, load='_classic_read'):
        """
        Caso o contexto contenha ``filtrar_responsavel`` e ``filtrar_solicitante``, filtra de acordo com o domain
        gerado no método ``read_context()``
        :param fields:
        :param load:
        :return:
        """
        # Quando o domain é [], todos os itens são selecionados
        recs = self.search(self.filtra_responsavel())
        # Lista de ids permitidos de acordo com o contexto
        ids = tuple([rec.id for rec in recs])
        # Nova lista filtrada
        self._ids = tuple([_id for _id in self._ids if _id in ids])
        return super(Reserva, self).read(fields, load)

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """
        Sobrescrito para considerar o domain baseado no ``filtra_responsavel``
        Adiciona ('dia_ids.espaco_id', 'in', <lista de espaços sob responsabilidade do usuário>)
        :param domain:
        :param fields:
        :param groupby:
        :param offset:
        :param limit:
        :param orderby:
        :param lazy:
        :return:
        """
        new_domain = self.filtra_responsavel()
        domain += new_domain
        return super(Reserva, self).read_group(domain, fields, groupby, offset, limit, orderby, lazy)

    def espacos_responsavel(self):
        """
        Localiza o objeto "responsavel" para o usuário e retorna os espaços associados
        :return:
        """
        responsavel = self.env['ud.reserva.responsavel'].search([
            ('pessoa_id', '=', self.env.uid)
        ])
        # Se o usuário não for responsável por nenhum espaço, levanta uma exceção de validação
        if not responsavel:
            raise ValidationError('Você não tem permissão para executar essa ação. Por favor entre '
                                  'em contato com administrador do sistema.')
        return responsavel.espaco_ids

    def espacos_solicitacao(self):
        """
        Localiza e retorna um set() de espacos usados na solicitação
        :return: RecordSet(): Conjunto de espaços da solicitação
        """
        espacos_solicitacao_ids = []
        for dia in self.dia_ids:
            espacos_solicitacao_ids.append(dia.espaco_id.id)
        return self.env['ud.espaco'].browse(espacos_solicitacao_ids)

    def verifica_responsavel(self):
        """
        Valida se o usuário atual é o responśavel por algum dos espaços na solicitação
        :return:
        """
        espacos_resp = self.espacos_responsavel()
        espacos_solicitacao = self.espacos_solicitacao()
        inter = espacos_resp & espacos_solicitacao
        if not inter:
            raise ValidationError('Você não é responsável por nenhum dos espaços dessa solicitação, '
                                  'em caso de dúvidas contate o administrador do sistema')

    @api.one
    def aprovar(self):
        """
        Verifica se o usuário tem responsabilidade sobre o espaço.
        Aprova a reserva.
        :return:
        """
        self.verifica_responsavel()
        # Adiciona os espaços aprovados na lista
        espacos_resp = self.espacos_responsavel()
        espacos_solicitacao = self.espacos_solicitacao()
        for espaco in espacos_resp:
            if espaco in espacos_solicitacao:
                self.espaco_aprovado_ids |= espaco
        # Aprova ou coloca em aguardando aprovação
        if self.state in ["enviada", 'aguardando_aprovacao']:
            if len(self.espaco_aprovado_ids) == len(espacos_solicitacao):
                self.state = 'aprovada'
            else:
                self.state = 'aguardando_aprovacao'

    @api.one
    def cancelar(self, motivo, data_cancelamento):
        """
        Executa o cancelamento atualizando o motivo e a data.
        :param motivo: Texto repassado no wizard de cancelamento
        :param data_cancelamento: Data adicionada automaticamente ao registrar o cancelamento
        :return:
        """
        if not self.motivo_cancelamento:
            self.data_cancelamento = data_cancelamento
            self.state = 'cancelada'
            self.motivo_cancelamento = motivo

    @api.model
    def create(self, vals):
        """
        Muda o status da solicitação de reserva para 'enviada'
        :param vals:
        :return:
        """
        vals['state'] = 'enviada'
        return super(Reserva, self).create(vals)

    @api.constrains('dia_ids', 'solicitante_id', 'titulo', 'descricao', 'state')
    def valida_responsavel(self):
        """
        Verifica se o usuário é o solicitante ou o responsável pelo espaço.
        :return:
        :raise: ValidationError: Quando o usuário não se encaixa na regra
        """
        usuario = self.env.user
        grupo_gerente = self.env.ref('ud_reserva.gerente_reserva')
        if grupo_gerente in usuario.groups_id and self.solicitante_id != usuario:
            self.verifica_responsavel()