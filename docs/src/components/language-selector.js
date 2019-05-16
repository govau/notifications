import React, { createContext, Fragment } from 'react'
import styled, { css } from 'styled-components'
import Select from 'react-select'
import PropTypes from 'prop-types'

import { H3 } from './core/heading'
import { languages } from '../config'

const Nav = styled.nav`
  display: flex;
  border-bottom: 4px solid #313131;
`

const LanguageLink = styled.button`
  cursor: pointer;
  border: 0;
  background-color: #e8fafc;

  ${props =>
    props.active
      ? css`
          text-decoration: underline;
          font-weight: bold;
          background-color: #313131;
          color: white;
        `
      : css``};
`

// spearate wrapper to get around props interpolation on LanguageLink
const NavLanguageLink = styled(LanguageLink)`
  padding: 1em 1em;
  flex: 1 1 auto;
  text-align: center;

  & + & {
    margin-left: 2px;
  }
`

const createLanguageOption = language => ({
  value: language,
  label: languages[language],
})

const languageOptions = Object.keys(languages)
  .sort()
  .map(createLanguageOption)

// Pretty-print the current language
const getLanguageLabel = language => languages[language]

const Context = createContext({
  current: '',
  changeLanguage: language => {},
})

// Wrap everything in this to give access to a current language. You can nest
// this to give a sub-current-language.
class Provider extends React.Component {
  state = { current: this.props.initial || languageOptions[0].value }

  changeLanguage = current => {
    this.setState({ current })
  }

  render() {
    return (
      <Context.Provider
        {...this.props}
        value={{
          current: this.state.current,
          changeLanguage: this.changeLanguage,
        }}
      />
    )
  }
}

// Language selector. Pop this anywhere inside a provider context to allow for
// language selection.
const Languages = props => (
  <Context.Consumer>
    {({ current, changeLanguage }) => (
      <Fragment>
        <H3>Select language</H3>
        <Nav>
          {languageOptions.map(({ value, label }) => (
            <NavLanguageLink
              active={value === current}
              key={label}
              onClick={() => {
                changeLanguage(value)
                props.onChange(value)
              }}
            >
              {label}
            </NavLanguageLink>
          ))}
        </Nav>
      </Fragment>
    )}
  </Context.Consumer>
)

Languages.propTypes = {
  /** Called when a language is selected. Selected language is passed as only parameter. */
  onChange: PropTypes.func,
}

Languages.defaultProps = {
  onChange: () => {},
}

const Selector = props => (
  <Context.Consumer>
    {({ current, changeLanguage }) => (
      <Select
        isSearchable={false}
        styles={{
          control: provided => ({
            ...provided,
          }),
        }}
        value={createLanguageOption(current)}
        options={languageOptions}
        onChange={({ value }) => changeLanguage(value)}
      />
    )}
  </Context.Consumer>
)

// Get the current language
const CurrentLanguage = ({ children }) => (
  <Context.Consumer>{({ current }) => children(current)}</Context.Consumer>
)

export {
  Languages as default,
  Selector,
  CurrentLanguage,
  Provider,
  getLanguageLabel,
}
