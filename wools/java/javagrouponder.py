from wools.java.javanodewrapper import JavaNodeWrapper
from . import javautils as ju
from .wool import PARENT

from alpakka.templates import template_var
from collections import OrderedDict
import re


class JavaGrouponder(JavaNodeWrapper):

    def __init__(self, *args):
        super(JavaGrouponder, self).__init__(*args)
        # find all available variables in the sub-statements
        self.vars = OrderedDict()
        for item in self.children.values():
            java_name = re.sub(r'^_', '', item.yang_name())
            java_name = ju.to_camelcase(java_name)
            self.vars[java_name] = item
        for uses in self.uses.values():
            for name in uses.children.keys():
                java_name = re.sub(r'^_', '', name)
                java_name = ju.to_camelcase(java_name)
                self.vars.pop(java_name)
        for item in list(self.uses.values()):
            self.uses[ju.java_class_name(item.yang_name())] = \
                self.uses.pop(item.yang_name())

    @template_var
    def inherited_vars(self):
        """
        Collects a dictionary of inherited variables that are needed for
        super calls.
        :return: dictionary of inherited variables
        """
        result = OrderedDict()
        for name, parent_group in self.uses.items():
            # collect variables that are inherited by the parent
            for inh_name, var in parent_group.inherited_vars().items():
                result[inh_name] = var
            # collect variables available in the parent class
            for var_name, var in parent_group.vars.items():
                result[var_name] = var
        return result

    @template_var
    def imports(self):
        """
        Collects all the imports that are needed for the grouping.
        :return: set of imports
        """
        imports = ju.ImportDict()
        # imports from children
        for child in self.children.values():
            imports.merge(child.java_imports)
        # imports from super classes
        for inherit in self.uses.values():
            imports.merge(inherit.inheritance_imports())
        for var in self.vars.values():
            # checking if there is at least one list defined in the grouponder
            if hasattr(var, 'group') and var.group == 'list':
                imports.add_import(ju.JAVA_LIST_INSTANCE_IMPORTS[0],
                                   ju.JAVA_LIST_INSTANCE_IMPORTS[1])
                break
        return imports.get_imports()


class JavaContainer(JavaGrouponder, PARENT['container']):

    def __init__(self, statement, parent):
        super(JavaContainer, self).__init__(statement, parent)
        self.java_imports = ju.ImportDict()
        # FIXME: remove special handling for Tapi, not needed any more
        if 'tapi' in self.top().yang_module() and self.parent == self.top():
            # fixing name collision in the ONF TAPI: context
            self.java_type = self.generate_java_type()
            for ch_name, ch_wrapper in self.children.items():
                # store the yang name
                ch_wrapper.name = ch_wrapper.yang_name()
                # remove leading underscores from the name
                java_name = re.sub(r'^_', '', ch_wrapper.name)
                java_name = ju.to_camelcase(java_name)
                self.vars[java_name] = ch_wrapper
                self.top().add_class(self.java_type, self)
                self.java_imports.add_import(self.package(), self.java_type)
            # containers that just import a grouping don't need a new class
            # -> variable
        elif len(self.uses) == 1 and len(self.vars) == 0:
            class_item = next(iter(self.uses.values()))
            self.java_type = class_item.generate_java_type()
            self.java_imports = class_item.java_imports
        else:
            # process exception when statement has i_children but no variables
            if len(statement.i_children) > 0 and len(self.vars) == 0:
                # adding variables to container class class
                for child in self.children.values():
                    if child.yang_type() in [
                        'container', 'grouping', 'list', 'leaf-list',
                    ]:
                        child.name = child.yang_name()
                        java_name = ju.to_camelcase(child.name)
                        self.vars[java_name] = child
            self.java_type = self.generate_java_type()
            self.top().add_class(self.java_type, self)
            self.java_imports.add_import(self.package(), self.java_type)

    @template_var
    def member_imports(self):
        """
        :return: imports needed if this class is a member
        """
        return self.java_imports


class JavaList(JavaGrouponder, PARENT['list']):

    def __init__(self, statement, parent):
        super(JavaList, self).__init__(statement, parent)
        self.group = 'list'
        self.java_imports = ju.ImportDict()
        # TODO: einmalig genutzt, wirklich als globale variable
        self.java_imports.add_import(ju.JAVA_LIST_IMPORTS[0],
                                     ju.JAVA_LIST_IMPORTS[1])
        # check if a super class exists and assign type
        if self.uses:
            # multiple inheritance is not supported in Java:
            # importing all variables
            if len(self.uses) > 1:
                for use in self.uses.values():
                    for child in use.children.values():
                        java_name = ju.to_camelcase(child.yang_name())
                        self.vars[java_name] = child
            # only one super class -> assign type
            else:
                self.type = next(iter(self.uses.values()))
                self.java_imports.merge(self.type.java_imports)
        # check for any other children not already in the variable list and
        # add them
        # FIXME: the 'if' might not work correctly
        # for child_wr in self.children.values():
        #     if child_wr not in self.vars.values():
        #         child_wr.name = child_wr.statement.arg
        #         java_name = to_camelcase(child_wr.statement.arg)
        #         self.vars[java_name] = child_wr
        # if new variables are defined in the list, a helper class is needed
        # FIXME: the commented code (previous fixme) breaks this check
        if self.children and 0 < len(self.vars):
            self.element_type = (self.generate_java_type() +
                                 ju.JAVA_LIST_CLASS_APPENDIX)
            self.top().add_class(self.element_type, self)
            self.java_type = 'List<%s>' % self.element_type
            self.java_imports.add_import(self.package(), self.element_type)
        else:
            # if a type is defined use it
            if hasattr(self, 'type') and hasattr(self.type, 'java_type'):
                self.element_type = self.type.java_type
                self.java_type = 'List<%s>' % self.type.java_type
            # unknown list elements
            else:
                self.java_type = 'List'
        # collect list of keys
        self.keys = [ju.to_camelcase(key) for key in self.keys]


class JavaGrouping(JavaGrouponder, PARENT['grouping']):

    def __init__(self, statement, parent):
        super(JavaGrouping, self).__init__(statement, parent)
        self.java_type = self.generate_java_type()
        self.java_imports = ju.ImportDict()
        self.java_imports.add_import(self.package(), self.java_type)
        self.top().add_class(self.java_type, self)
        for sub_st in statement.substmts:
            if sub_st.keyword == 'choice':
                for case in sub_st.substmts:
                    if case.keyword == 'case':
                        java_name = ju.to_camelcase(re.sub(r'^_', '',
                                                           case.arg))
                        var = JavaCase(case, self)
                        var.name = case.arg
                        self.vars[java_name] = var

    @template_var
    def type(self):
        # FIXME: needs fixing for more than one uses
        if not self.vars:
            if len(self.uses) == 1:
                return next(self.uses.keys())
        else:
            return None

    @template_var
    def inheritance_imports(self):
        """
        :return: Imports needed if inheriting from this class.
        """
        return self.java_imports

    @template_var
    def member_imports(self):
        return self.java_imports


class JavaCase(JavaGrouponder, PARENT['case']):

    def __init__(self, statement, parent):
        super(JavaCase, self).__init__(statement, parent)
        self.java_imports = ju.ImportDict()
        self.java_type = self.generate_java_type() + 'CaseType'
        self.top().add_class(self.java_type, self)
        self.java_imports.add_import(self.package(), self.java_type)


class JavaChoice(JavaGrouponder, PARENT['choice']):

    def __init__(self, statement, parent):
        super(JavaChoice, self).__init__(statement, parent)


class JavaInput(JavaGrouponder, PARENT['input']):

    def __init__(self, statement, parent):
        super(JavaInput, self).__init__(statement, parent)


class JavaOutput(JavaGrouponder, PARENT['output']):

    def __init__(self, statement, parent):
        super(JavaOutput, self).__init__(statement, parent)
